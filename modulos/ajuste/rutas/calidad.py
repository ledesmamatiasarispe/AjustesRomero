# rutas/calidad.py -- puerto del PRIMER CORTE de backend/routers/calidad.py de ajuste_comp_web (confirmado con
# el usuario en la app vieja): ABM de informes (formulario + guardado/listado/grupos/borradores/archivado) +
# la integración "generar informe desde una sesión de Historicos" (completa el pendiente que historicos.py
# dejaba anotado). Explícitamente FUERA de este corte, igual que en la app vieja:
#   - Análisis de imágenes por OpenCV (conteo nódulos/grafito laminar, calibración) -- va con el módulo Cámara.
#   - Automatización COM con Access ("Fundiciones-2010PRG") -- va con el módulo Fundiciones.
#   - Impresión de grupos a HTML -- nunca se portó ni en la app vieja (confirmado en su propio comentario de
#     alcance: "impresión no"), no es una regresión de esta migración.
#   - Comparar informes / "ver comp. estimada" (ventanas standalone).
#
# Modelo de datos: igual que el original, un "informe" es un dict plano (ver REPORT_FIELDS) guardado en
# datos.load_quality_reports()/save_quality_reports() (reemplaza TODA la lista cada vez, mismo patrón que
# save_alloys/save_thermal_device_records). Se agrupan por (base, lote) -- una "colada" puede tener un informe
# por cada material final de esa base.
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import datos
from .. import dispositivos as devices
from ..utils import fmt, to_float

router = APIRouter(prefix="/api/calidad", tags=["calidad"])

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
DEFAULT_SECTION_OPTIONS = ["Hasta 13 mm", "De 12 a 25 mm", "De 20 a 50 mm"]

REPORT_FIELDS = (
    "fecha", "base", "base_display", "material", "family", "lote", "informe",
    "ce_final", "c_final", "si_final", "datos",
    "traccion", "traccion_real", "seccion", "dureza", "tam_grafito",
    "morfologia", "tipo_grafito", "conteo_nodulos", "pct_nodularizacion", "alargamiento",
    "estiramiento_real", "tension_real_lim_prop", "mg_disuelto",
    "perlita", "ferrita", "matriz",
)


def _unique_keep_order(items):
    out = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


# ---------- catálogo de materiales finales (calidad_meta, viene de Catálogo) ----------

def _catalog_final_entry(alloy):
    meta = alloy.get("calidad_meta", {}) if isinstance(alloy, dict) else {}
    if not isinstance(meta, dict) or not meta.get("es_material_final"):
        return None
    code = str(meta.get("codigo") or alloy.get("nombre", "")).strip()
    if not code:
        return None
    bases = [str(b).strip() for b in (meta.get("bases") or []) if str(b).strip()]
    family = str(meta.get("family") or "").strip()
    defaults = meta.get("defaults", {}) if isinstance(meta.get("defaults", {}), dict) else {}
    section_options = [str(opt).strip() for opt in (meta.get("section_options") or []) if str(opt).strip()]
    return {
        "code": code,
        "name": alloy.get("nombre", code),
        "bases": _unique_keep_order(bases),
        "family": family,
        "defaults": dict(defaults),
        "section_options": section_options or list(DEFAULT_SECTION_OPTIONS),
    }


def _load_final_catalog():
    """Arma {codigo: entry}, {base: [materiales]}, {material: [bases]} a partir del catálogo real
    (Catálogo > Aleación final > es_material_final)."""
    alloys = datos.load_alloys()
    final_materials = {}
    base_to_materials = {}
    material_to_bases = {}
    for alloy in alloys:
        entry = _catalog_final_entry(alloy)
        if not entry:
            continue
        code = entry["code"]
        final_materials[code] = entry
        for base in entry["bases"]:
            base_to_materials.setdefault(base, []).append(code)
            material_to_bases.setdefault(code, []).append(base)

    def _sort_key(val):
        return (int(val) if str(val).isdigit() else 9999, str(val))

    for base, mats in list(base_to_materials.items()):
        base_to_materials[base] = sorted(_unique_keep_order(mats), key=_sort_key)
    for mat, bases in list(material_to_bases.items()):
        material_to_bases[mat] = sorted(_unique_keep_order(bases), key=_sort_key)
    return final_materials, base_to_materials, material_to_bases, alloys


def _base_codes(base_to_materials):
    def _sort_key(val):
        return (int(val) if str(val).isdigit() else 9999, str(val))
    return sorted(base_to_materials.keys(), key=_sort_key)


def _material_defaults(final_materials, material):
    return dict(final_materials.get(str(material or "").strip(), {}).get("defaults", {}))


def _section_options_for_material(final_materials, material):
    entry = final_materials.get(str(material or "").strip(), {})
    return list(entry.get("section_options", DEFAULT_SECTION_OPTIONS))


def _default_section_for_material(final_materials, material):
    options = _section_options_for_material(final_materials, material)
    if not options:
        return ""
    return options[1] if len(options) > 1 else options[0]


def _family_for_material(final_materials, material):
    return str(final_materials.get(str(material or "").strip(), {}).get("family", "")).strip()


def _family_for_report(report, final_materials):
    if not isinstance(report, dict):
        return ""
    family = str(report.get("family", "")).strip()
    if family:
        return family
    return _family_for_material(final_materials, report.get("material", ""))


def _family_for_reports(reports, final_materials):
    families = _unique_keep_order(_family_for_report(r, final_materials) for r in reports if _family_for_report(r, final_materials))
    if not families:
        return ""
    if len(families) == 1:
        return families[0]
    return "Mixto"


def _default_morfologia_value(final_materials, material, defaults):
    if _family_for_material(final_materials, material) == "Nodular":
        return ""
    return defaults.get("morfologia", "")


def _get_final_alloy_by_code(alloys, code):
    for a in alloys:
        meta = a.get("calidad_meta", {}) if isinstance(a, dict) else {}
        if not isinstance(meta, dict) or not meta.get("es_material_final"):
            continue
        c = str(meta.get("codigo") or a.get("nombre", "")).strip()
        if c == str(code).strip():
            return a
    return None


def _build_inoc_snapshot(alloys, material_code, base=None):
    alloy = _get_final_alloy_by_code(alloys, material_code) or {}
    meta = alloy.get("inoculacion_meta", {}) if isinstance(alloy, dict) else {}
    return {
        "inoculacion_meta": meta,
        "base_resuelta": str(base or "").strip(),
        "protocolo": datos.resolve_inoc_protocol(meta, base=base),
    }


# ---------- informes: normalización / validación ----------

def _normalize_report_images(images):
    normalized = []
    used_ids = set()
    for item in images or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        nombre = str(item.get("nombre") or Path(path).name).strip() or Path(path).name
        image_id = str(item.get("id") or uuid.uuid4().hex)
        while image_id in used_ids:
            image_id = uuid.uuid4().hex
        used_ids.add(image_id)
        normalized.append({
            "id": image_id,
            "nombre": nombre,
            "path": path,
            "comentario": str(item.get("comentario") or "").strip(),
            "added_at": str(item.get("added_at") or ""),
        })
    return normalized


_COMPLETENESS_FIELDS = (
    "fecha", "material", "lote", "ce_final", "dureza",
    "morfologia", "tipo_grafito", "conteo_nodulos", "pct_nodularizacion",
    "perlita", "ferrita",
)


def _report_completeness_tag(report):
    if report.get("_draft_pending"):
        return "draft"
    # Exigir solo campos visibles para esta familia (frontend syncFamilyFields). Nodular oculta morfología y
    # tipo de grafito; Gris oculta los campos de nódulos. Tracción real Lab sigue siendo opcional y tiene su
    # indicador independiente.
    family = str(report.get("_family_resolved") or report.get("family") or "").strip()
    fields = set(_COMPLETENESS_FIELDS)
    if family == "Nodular":
        fields.difference_update(("morfologia", "tipo_grafito"))
    else:
        fields.difference_update(("conteo_nodulos", "pct_nodularizacion"))
        if family != "Gris":
            fields.discard("tipo_grafito")
    missing = any(report.get(f) is None or not str(report.get(f, "")).strip() for f in fields)
    has_photo = bool(_normalize_report_images(report.get("imagenes", [])))
    return "complete" if (not missing and has_photo) else "incomplete"


def _informe_group_base(report):
    text = str(report.get("informe", "") or "")
    return re.sub(r"\s*-\s*mat\s+\S+\s*$", "", text).strip()


def _validate_micro(payload):
    """Perlita/ferrita deben venir juntas y sumar 100 si hay algún dato de microestructura cargado."""
    def _opt_float(key):
        raw = str(payload.get(key, "") or "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    perlita = _opt_float("perlita")
    ferrita = _opt_float("ferrita")
    any_micro = perlita is not None or ferrita is not None
    if any_micro and (perlita is None or ferrita is None):
        raise HTTPException(status_code=400, detail={"error": "perlita_ferrita_incompletas"})
    if perlita is not None and ferrita is not None and abs((perlita + ferrita) - 100.0) > 1e-6:
        raise HTTPException(status_code=400, detail={"error": "microestructura_no_suma_100"})


def _clean_report_patch(payload):
    """Solo deja pasar los campos de REPORT_FIELDS -- nunca confiar en el cliente para "id"/"archived"/flags
    de borrador, esos los maneja el backend."""
    return {k: str(payload.get(k, "") or "").strip() if k != "imagenes" else payload.get(k)
            for k in REPORT_FIELDS if k in payload}


# ---------- endpoints: catálogo ----------

@router.get("/catalog")
def get_catalog(_: dict = Depends(devices.require_acceso)):
    final_materials, base_to_materials, material_to_bases, _alloys = _load_final_catalog()
    bases = _base_codes(base_to_materials)
    return {
        "bases": bases,
        "base_to_materials": base_to_materials,
        "materials": {
            code: {
                "family": entry["family"],
                "bases": entry["bases"],
                "defaults": entry["defaults"],
                "section_options": entry["section_options"],
                "default_section": _default_section_for_material(final_materials, code),
            }
            for code, entry in final_materials.items()
        },
    }


# ---------- endpoints: alerta mensual Gris/Nodular ----------
# Avisa si todavía no se cargó, EN EL MES EN CURSO, al menos un informe con material Gris y uno Nodular
# (control de calidad mínimo mensual por familia). "family" ya queda guardado en cada informe al elegir el
# material -- no hace falta volver a inferirlo acá. Cuenta informes archivados también: lo que importa es si
# se hizo el ensayo ese mes, no si el papel se archivó después.

@router.get("/alerta-mensual")
def get_alerta_mensual(_: dict = Depends(devices.require_acceso)):
    mes_actual = datetime.now().strftime("%Y-%m")
    reports = datos.load_quality_reports()
    familias_del_mes = {
        str(r.get("family", "") or "").strip()
        for r in reports
        if isinstance(r, dict) and str(r.get("fecha", "") or "").strip()[:7] == mes_actual
    }
    faltan = [f for f in ("Gris", "Nodular") if f not in familias_del_mes]
    return {"mes": mes_actual, "faltan": faltan}


# ---------- endpoints: informes ----------

@router.get("/reports")
def list_reports(_: dict = Depends(devices.require_acceso)):
    reports = datos.load_quality_reports()
    final_materials, _b, _m, _a = _load_final_catalog()
    out = []
    for r in reports:
        r = dict(r)
        r["_family_resolved"] = _family_for_report(r, final_materials)
        r["_completeness"] = _report_completeness_tag(r)
        out.append(r)
    return {"reports": out}


@router.post("/reports")
def upsert_report(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Crea o actualiza UN informe (modo individual, no grupal). Si payload trae "id" y existe, actualiza;
    si no, crea uno nuevo."""
    final_materials, base_to_materials, material_to_bases, alloys = _load_final_catalog()
    base = str(payload.get("base", "") or "").strip()
    material = str(payload.get("material", "") or "").strip()
    if base not in base_to_materials:
        raise HTTPException(status_code=400, detail={"error": "base_invalida"})
    if material not in base_to_materials.get(base, []):
        raise HTTPException(status_code=400, detail={"error": "material_no_corresponde_a_base"})
    _validate_micro(payload)

    reports = datos.load_quality_reports()
    report_id = str(payload.get("id", "") or "").strip()
    existing_idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None) if report_id else None

    clean = _clean_report_patch(payload)
    clean["family"] = _family_for_material(final_materials, material)
    clean["morfologia"] = "" if clean["family"] == "Nodular" else clean.get("morfologia", "")
    clean["imagenes"] = _normalize_report_images(payload.get("imagenes", []))
    clean["_draft_pending"] = False
    clean["_draft_base"] = None
    clean["_draft_fields"] = []

    if existing_idx is None:
        clean["id"] = report_id or uuid.uuid4().hex
        clean.setdefault("archived", False)
        clean.setdefault("archived_at", "")
        clean["inoculacion_snapshot"] = _build_inoc_snapshot(alloys, material, base)
        reports.append(clean)
    else:
        prev = reports[existing_idx]
        clean["id"] = prev.get("id") or report_id or uuid.uuid4().hex
        clean["archived"] = prev.get("archived", False)
        clean["archived_at"] = prev.get("archived_at", "")
        clean["inoculacion_snapshot"] = prev.get("inoculacion_snapshot") or _build_inoc_snapshot(alloys, material, base)
        reports[existing_idx] = clean

    datos.save_quality_reports(reports)
    saved = next(r for r in reports if r.get("id") == clean["id"])
    return saved


@router.patch("/reports/{report_id}")
def patch_report_draft(report_id: str, payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Autoguardado de borrador: a diferencia de POST /reports, esto NO valida ni confirma -- guarda el
    estado actual del formulario marcado como _draft_pending=True, conservando el último estado confirmado en
    _draft_base para poder "Cancelar" después. Body: {"patch": {...campos...}}."""
    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    current = reports[idx]
    base_report = current.get("_draft_base") if current.get("_draft_pending") and isinstance(current.get("_draft_base"), dict) else {
        k: v for k, v in current.items() if k not in ("_draft_pending", "_draft_base", "_draft_fields")
    }
    patch = payload.get("patch") or {}
    draft = dict(current)
    draft.update(_clean_report_patch(patch))
    if "imagenes" in patch:
        draft["imagenes"] = _normalize_report_images(patch.get("imagenes"))
    draft["_draft_pending"] = True
    draft["_draft_base"] = base_report
    draft["_draft_fields"] = sorted(patch.keys())
    reports[idx] = draft
    datos.save_quality_reports(reports)
    return draft


@router.post("/reports/{report_id}/cancel-draft")
def cancel_report_draft(report_id: str, _: dict = Depends(devices.require_acceso_editor)):
    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    report = reports[idx]
    base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
    if not base_report:
        return report
    restored = dict(base_report)
    restored["_draft_pending"] = False
    restored["_draft_base"] = None
    restored["_draft_fields"] = []
    reports[idx] = restored
    datos.save_quality_reports(reports)
    return restored


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, _: dict = Depends(devices.require_acceso_editor)):
    reports = datos.load_quality_reports()
    new_reports = [r for r in reports if r.get("id") != report_id]
    if len(new_reports) == len(reports):
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    datos.save_quality_reports(new_reports)
    return {"ok": True}


# ---------- endpoints: grupo (base + lote) ----------

@router.post("/reports/group")
def save_group(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Edición en bloque de TODO un grupo (base+lote): aplica el mismo patch a cada informe del grupo, con
    "informe" siempre re-armado como "{valor} - mat {material}" por informe."""
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    patch = _clean_report_patch(payload.get("patch") or {})
    reports = datos.load_quality_reports()
    indexes = [i for i, r in enumerate(reports) if r.get("base", "") == base and r.get("lote", "") == lote]
    if not indexes:
        raise HTTPException(status_code=404, detail={"error": "grupo_no_encontrado"})
    for idx in indexes:
        report = dict(reports[idx])
        material = report.get("material", "")
        for key, value in patch.items():
            if key == "informe":
                report["informe"] = f"{value} - mat {material}" if value else report.get("informe", "")
            else:
                report[key] = value
        report["_draft_pending"] = False
        report["_draft_base"] = None
        report["_draft_fields"] = []
        reports[idx] = report
    datos.save_quality_reports(reports)
    return {"ok": True, "updated": len(indexes)}


@router.patch("/reports/group/draft")
def draft_group(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    patch = _clean_report_patch(payload.get("patch") or {})
    reports = datos.load_quality_reports()
    indexes = [i for i, r in enumerate(reports) if r.get("base", "") == base and r.get("lote", "") == lote]
    if not indexes:
        raise HTTPException(status_code=404, detail={"error": "grupo_no_encontrado"})
    for idx in indexes:
        current = reports[idx]
        material = current.get("material", "")
        base_report = current.get("_draft_base") if current.get("_draft_pending") and isinstance(current.get("_draft_base"), dict) else {
            k: v for k, v in current.items() if k not in ("_draft_pending", "_draft_base", "_draft_fields")
        }
        draft = dict(current)
        for key, value in patch.items():
            if key == "informe":
                draft["informe"] = f"{value} - mat {material}" if value else draft.get("informe", "")
            else:
                draft[key] = value
        draft["_draft_pending"] = True
        draft["_draft_base"] = base_report
        draft["_draft_fields"] = sorted(patch.keys())
        reports[idx] = draft
    datos.save_quality_reports(reports)
    return {"ok": True, "updated": len(indexes)}


@router.post("/reports/group/cancel-draft")
def cancel_group_draft(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    reports = datos.load_quality_reports()
    indexes = [i for i, r in enumerate(reports) if r.get("base", "") == base and r.get("lote", "") == lote]
    for idx in indexes:
        report = reports[idx]
        base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
        if base_report:
            restored = dict(base_report)
            restored["_draft_pending"] = False
            restored["_draft_base"] = None
            restored["_draft_fields"] = []
            reports[idx] = restored
    datos.save_quality_reports(reports)
    return {"ok": True}


@router.delete("/reports/group")
def delete_group(base: str = Query(...), lote: str = Query(...), _: dict = Depends(devices.require_acceso_editor)):
    reports = datos.load_quality_reports()
    new_reports = [r for r in reports if not (r.get("base", "") == base and r.get("lote", "") == lote)]
    removed = len(reports) - len(new_reports)
    if removed <= 0:
        raise HTTPException(status_code=404, detail={"error": "grupo_no_encontrado"})
    datos.save_quality_reports(new_reports)
    return {"ok": True, "removed": removed}


@router.post("/reports/group/archive")
def archive_group(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    reports = datos.load_quality_reports()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archived = 0
    for r in reports:
        if r.get("base", "") == base and r.get("lote", "") == lote and not r.get("archived"):
            r["archived"] = True
            r["archived_at"] = stamp
            archived += 1
    if archived:
        datos.save_quality_reports(reports)
    return {"ok": True, "archived": archived}


@router.post("/reports/group/add-materials")
def add_materials_to_group(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Agrega informes nuevos (con los defaults del catálogo) para materiales de la MISMA base que todavía no
    tienen informe en este lote, copiando fecha/ce/c/si/datos del primer informe existente del grupo como
    plantilla."""
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    materials = [str(m).strip() for m in (payload.get("materials") or []) if str(m).strip()]
    if not materials:
        raise HTTPException(status_code=400, detail={"error": "sin_materiales"})

    final_materials, base_to_materials, _m, _alloys = _load_final_catalog()
    reports = datos.load_quality_reports()
    existing = [r for r in reports if r.get("base", "") == base and r.get("lote", "") == lote]
    if not existing:
        raise HTTPException(status_code=404, detail={"error": "grupo_no_encontrado"})
    existing_materials = {r.get("material", "") for r in existing}
    template = existing[0]
    added = []
    for material in materials:
        if material not in base_to_materials.get(base, []) or material in existing_materials:
            continue
        defaults = _material_defaults(final_materials, material)
        family = _family_for_material(final_materials, material)
        report = {
            "id": uuid.uuid4().hex,
            "fecha": template.get("fecha", ""),
            "base": base,
            "base_display": template.get("base_display", base),
            "material": material,
            "family": family,
            "lote": lote,
            "informe": f"Informe calidad {family} {lote} - mat {material}".strip(),
            "ce_final": template.get("ce_final", ""),
            "c_final": template.get("c_final", ""),
            "si_final": template.get("si_final", ""),
            "datos": template.get("datos", ""),
            "traccion": defaults.get("traccion", ""),
            "traccion_real": "",
            "seccion": defaults.get("seccion", _default_section_for_material(final_materials, material)),
            "dureza": defaults.get("dureza", ""),
            "tam_grafito": defaults.get("tam_grafito", ""),
            "morfologia": _default_morfologia_value(final_materials, material, defaults),
            "tipo_grafito": defaults.get("tipo_grafito", ""),
            "conteo_nodulos": defaults.get("conteo_nodulos", ""),
            "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
            "alargamiento": defaults.get("alargamiento", ""),
            "estiramiento_real": "",
            "tension_real_lim_prop": "",
            "mg_disuelto": "",
            "perlita": defaults.get("perlita", ""),
            "ferrita": defaults.get("ferrita", ""),
            "matriz": "",
            "imagenes": [],
            "archived": False,
            "archived_at": "",
            "_draft_pending": False,
            "_draft_base": None,
            "_draft_fields": [],
            "inoculacion_snapshot": _build_inoc_snapshot(_alloys, material, base),
        }
        reports.append(report)
        added.append(report["id"])
    if added:
        datos.save_quality_reports(reports)
    return {"ok": True, "added": added}


# ---------- endpoints: imágenes ----------

@router.post("/reports/{report_id}/images")
def upload_image(report_id: str, file: UploadFile = File(...), _: dict = Depends(devices.require_acceso_editor)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail={"error": "formato_no_permitido"})
    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})

    dest_dir = Path(datos.ensure_quality_images_dir())
    dest_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{suffix}"
    dest = dest_dir / dest_name
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    image = {
        "id": uuid.uuid4().hex,
        "nombre": file.filename or dest_name,
        "path": str(dest),
        "comentario": "",
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    report = dict(reports[idx])
    report["imagenes"] = _normalize_report_images(list(report.get("imagenes", [])) + [image])
    reports[idx] = report
    datos.save_quality_reports(reports)
    return image


@router.patch("/reports/{report_id}/images/{image_id}")
def edit_image_comment(report_id: str, image_id: str, payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    report = dict(reports[idx])
    images = _normalize_report_images(report.get("imagenes", []))
    found = False
    for image in images:
        if image["id"] == image_id:
            image["comentario"] = str(payload.get("comentario", "") or "").strip()
            found = True
    if not found:
        raise HTTPException(status_code=404, detail={"error": "imagen_no_encontrada"})
    report["imagenes"] = images
    reports[idx] = report
    datos.save_quality_reports(reports)
    return {"ok": True}


@router.delete("/reports/{report_id}/images/{image_id}")
def remove_image(report_id: str, image_id: str, _: dict = Depends(devices.require_acceso_editor)):
    """Solo desvincula la imagen del informe (no borra el archivo del disco)."""
    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    report = dict(reports[idx])
    images = _normalize_report_images(report.get("imagenes", []))
    report["imagenes"] = [im for im in images if im["id"] != image_id]
    reports[idx] = report
    datos.save_quality_reports(reports)
    return {"ok": True}


@router.get("/images/{filename}")
def get_image(filename: str, _: dict = Depends(devices.require_acceso)):
    path = Path(datos.ensure_quality_images_dir()) / filename
    if ".." in filename or not path.exists():
        raise HTTPException(status_code=404, detail={"error": "imagen_no_encontrada"})
    return FileResponse(str(path))


# ---------- integración con Históricos: generar informe desde una sesión ----------

def _extract_material_code(texts, material_to_bases, base_to_materials):
    valid = set(material_to_bases.keys()) | set(base_to_materials.keys())
    for text in texts:
        raw = (text or "").strip()
        if not raw:
            continue
        if raw in valid:
            return raw
        lowered = raw.lower()
        for pattern in (r"\bmaterial\s*[:\-]?\s*0*(\d+)\b", r"\bmat\s*[:\-]?\s*0*(\d+)\b", r"\bbase\s*[:\-]?\s*0*(\d+)\b"):
            match = re.search(pattern, lowered)
            if not match:
                continue
            token = match.group(1)
            if token in valid:
                return token
            compact = token.lstrip("0") or "0"
            if compact in valid:
                return compact
        for token in re.findall(r"\d+", raw):
            if token in valid:
                return token
            compact = token.lstrip("0") or "0"
            if compact in valid:
                return compact
    return ""


def _infer_base_material_from_session(session, material_to_bases, base_to_materials):
    ajuste_objectives = [e.get("objetivo", "") for e in (session.get("ajustes") or []) if e.get("objetivo", "")]
    base_materials = []
    for text in ajuste_objectives:
        mat = _extract_material_code([text], material_to_bases, base_to_materials)
        if mat in base_to_materials:
            base_materials.append(mat)
    base_materials = _unique_keep_order(base_materials)
    if not base_materials:
        raise HTTPException(status_code=400, detail={"error": "sin_ajustes_validos"})

    union_materials = []
    for base in base_materials:
        union_materials.extend(base_to_materials.get(base, []))
    union_materials = _unique_keep_order(union_materials)
    if not union_materials:
        raise HTTPException(status_code=400, detail={"error": "sin_ajustes_validos"})

    actual_base = next(
        (base for base, mats in base_to_materials.items() if list(mats) == union_materials),
        base_materials[0],
    )
    return {
        "actual_base": actual_base,
        "display_base": "-".join(base_materials),
        "base_materials": base_materials,
        "materials": union_materials,
        "material_inferido": base_materials[-1],
    }


def _history_common_data(session, final_materials, base_to_materials, material_to_bases):
    ajustes = session.get("ajustes") or []
    calculos = session.get("calculos") or []
    entry = ajustes[-1] if ajustes else (calculos[-1] if calculos else {})

    fecha_full = session.get("ended_at") or entry.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    objective = session.get("objetivo", "")
    colada = session.get("colada", "")
    base_info = _infer_base_material_from_session(session, material_to_bases, base_to_materials)
    base = base_info["actual_base"]
    base_display = base_info["display_base"]
    material = base_info["material_inferido"]

    comp_fin = ((entry.get("estimado") or {}).get("comp") or {})
    ce_fin = entry.get("ce_estimado", "")

    lines = [f"Colada: {colada}", f"Objetivo: {objective}", f"Fecha cierre: {session.get('ended_at', '')}"]
    if not material:
        lines.extend(["", "Revision manual:", "No se pudo inferir automaticamente el material/base desde la colada u objetivo."])

    family_names = _unique_keep_order(_family_for_material(final_materials, m) for m in base_info["materials"] if _family_for_material(final_materials, m))
    family = family_names[0] if len(family_names) == 1 else ("Mixto" if family_names else "")
    prefix = f"Informe calidad {family}" if family else "Informe calidad"
    return {
        "fecha": fecha_full[:10],
        "base": base,
        "base_display": base_display,
        "material_inferido": material,
        "material_base": base_info["base_materials"][0] if len(base_info["base_materials"]) == 1 else "",
        "default_materials": list(base_info["base_materials"]),
        "materials": list(base_info["materials"]),
        "lote": colada,
        "informe_base": f"{prefix} base {base_display} {colada}".strip(),
        "datos": "\n".join(lines).strip(),
        "ce_final": fmt(to_float(ce_fin), 2),
        "c_final": fmt(comp_fin.get("C", 0.0), 2),
        "si_final": fmt(comp_fin.get("Si", 0.0), 2),
        "family": family,
    }


@router.get("/material-options")
def material_options_for_session(session_idx: int = Query(...), _: dict = Depends(devices.require_acceso)):
    history = datos.load_history()
    if session_idx < 0 or session_idx >= len(history):
        raise HTTPException(status_code=404, detail={"error": "sesion_no_encontrada"})
    final_materials, base_to_materials, material_to_bases, _alloys = _load_final_catalog()
    data = _history_common_data(history[session_idx], final_materials, base_to_materials, material_to_bases)
    return {
        "base": data["base"],
        "base_display": data["base_display"],
        "family": data["family"],
        "materials": data["materials"],
        "material_base": data["material_base"],
        "material_inferido": data["material_inferido"],
        "default_materials": data["default_materials"],
        "lote": data["lote"],
    }


@router.post("/generate-from-session")
def generate_from_session(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Crea/actualiza un informe por material seleccionado, prellenado con CE/C/Si finales y fecha/colada de
    la sesión + defaults del catálogo para cada material."""
    session_idx = payload.get("session_idx")
    history = datos.load_history()
    if session_idx is None or session_idx < 0 or session_idx >= len(history):
        raise HTTPException(status_code=404, detail={"error": "sesion_no_encontrada"})
    session = history[session_idx]

    final_materials, base_to_materials, material_to_bases, alloys = _load_final_catalog()
    data = _history_common_data(session, final_materials, base_to_materials, material_to_bases)
    base = data["base"]
    materials = [str(m).strip() for m in (payload.get("materials") or [])] or list(base_to_materials.get(base, []))
    if not materials:
        raise HTTPException(status_code=400, detail={"error": "sin_materiales"})

    reports = datos.load_quality_reports()
    updated_ids = []
    for material in materials:
        defaults = _material_defaults(final_materials, material)
        report = {
            "fecha": data["fecha"],
            "base": base,
            "base_display": data["base_display"],
            "material": material,
            "family": _family_for_material(final_materials, material),
            "lote": data["lote"],
            "informe": f"{data['informe_base']} - mat {material}",
            "datos": data["datos"],
            "ce_final": data["ce_final"],
            "c_final": data["c_final"],
            "si_final": data["si_final"],
            "traccion": defaults.get("traccion", ""),
            "traccion_real": "",
            "seccion": defaults.get("seccion", _default_section_for_material(final_materials, material)),
            "dureza": defaults.get("dureza", ""),
            "tam_grafito": defaults.get("tam_grafito", ""),
            "morfologia": _default_morfologia_value(final_materials, material, defaults),
            "tipo_grafito": defaults.get("tipo_grafito", ""),
            "conteo_nodulos": defaults.get("conteo_nodulos", ""),
            "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
            "alargamiento": defaults.get("alargamiento", ""),
            "estiramiento_real": "",
            "tension_real_lim_prop": "",
            "mg_disuelto": "",
            "perlita": defaults.get("perlita", ""),
            "ferrita": defaults.get("ferrita", ""),
            "matriz": "",
            "imagenes": [],
            "archived": False,
            "archived_at": "",
            "_draft_pending": False,
            "_draft_base": None,
            "_draft_fields": [],
            "inoculacion_snapshot": _build_inoc_snapshot(alloys, material, base),
        }
        existing_idx = next(
            (i for i, r in enumerate(reports) if r.get("base") == base and r.get("material") == material and r.get("lote") == data["lote"]),
            None,
        )
        if existing_idx is None:
            report["id"] = uuid.uuid4().hex
            reports.append(report)
        else:
            report["id"] = reports[existing_idx].get("id") or uuid.uuid4().hex
            reports[existing_idx] = report
        updated_ids.append(report["id"])

    datos.save_quality_reports(reports)
    return {"ok": True, "updated": len(updated_ids), "ids": updated_ids, "base": base, "lote": data["lote"]}
