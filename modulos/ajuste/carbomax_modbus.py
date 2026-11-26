# carbomax_modbus.py
"""
Lectura Modbus RTU del CARBOMAX DELTA por su interfaz RS485 (adaptador
RS485->USB local a esta PC, COM3) -- SEPARADA de la interfaz de red/IP que
ya usa el resto de la app (descarga HTTP de curvas via getallidx.cgi/etc.,
ver core/device_sync.py y decompiled/Extractor/CarbomaxDelta/ del
proyecto de escritorio). No es un puerto de la app de escritorio: esta
interfaz no existe ahi, es tooling nuevo.

Antecedente (no repetir el trabajo, ya esta hecho): diagnosticos/
explorar_modbus.py hizo un barrido completo de 0 a 65535 contra el
equipo real. Ver diagnosticos/barrido_*/comparacion_modbus.xlsx (hoja
"Alcance") para el detalle completo. Resumen:
  - Solo la funcion 03 (Read Holding Registers) responde. 01/02/04 nunca
    contestan nada (ni excepcion Modbus, timeout liso) -- confirmado de
    nuevo desde este modulo, no es un bug de un cliente en particular.
  - COM3, 57600 bps, 8N1, direccion de esclavo 1.
  - 128 registros con datos reales (direcciones 0-127); nada mas alla
    responde (probado individualmente 0-511, y por bloques hasta 65535).
  - Direcciones impares (1, 3, ...) devuelven el mismo par que la
    direccion par anterior -- no son palabras independientes.
  - QUIRK DEL EQUIPO: el campo "byte count" de la respuesta viene MAL
    para bloques que no arrancan en la direccion 0 (ej. pedir 32
    registros desde la direccion 32 devuelve un byte-count de 0x00 en
    vez de 0x40). El CRC sigue siendo valido sobre los bytes reales
    recibidos, y los datos de registro estan exactamente donde se
    esperaria si se ignora ese campo y se toman `cantidad*2` bytes a
    partir de ahi -- confirmado contra el barrido completo. Por eso
    `_read_registers`/`_read_bits` NO usan el byte-count declarado para
    cortar el payload, solo lo devuelven como dato de diagnostico.
  - Mapa de registros del modo CARBONO CONFIRMADO contra el equipo real
    (11/09/2026, tres mediciones distintas, número contra número igual a
    lo que mostró la pantalla): dentro del bloque de 26 registros de cada
    stand, offset +4=TF, +6=Pico, +8=TL, +10=CE%, +12=TS, +14=C%, +16=Si%
    (offset +2 queda sin identificar). El equipo tiene 4 "stands" de
    fábrica -- 1 y 2 en modo MICROESTRUTURA, 3 y 4 en modo CARBONO -- y
    cada uno ocupa un bloque de 26 registros: Stand 3 en 52-77, Stand 4 en
    78-103 (ver STAND_BLOCK_BASES/decode_carbono_block más abajo). El
    layout de MICROESTRUTURA también se confirmó parcialmente (TF/Pico/TL
    en los mismos offsets +4/+6/+8, CE en +10) pero sus campos TSE/TRE/
    REC/ΔREC no aparecen en ningún registro -- no expuestos por Modbus.

Este modulo tiene dos usos: exploracion en vivo (leer_todo, para la
pestaña web) y lectura de produccion para la deteccion automatica de
analisis nuevos (read_stand_block/decode_carbono_block, usados por
carbomax_modbus_auto.py).
"""
import struct

import serial

PORT = "COM3"
BAUDRATE = 57600
SLAVE_ID = 1
TIMEOUT = 0.6
MAX_REGISTER_QUANTITY = 125
MAX_BIT_QUANTITY = 2000

_EXCEPTION_MESSAGES = {
    1: "Funcion ilegal",
    2: "Direccion de dato ilegal",
    3: "Valor de dato ilegal",
    4: "Falla en el dispositivo esclavo",
    5: "Confirmacion (processing)",
    6: "Esclavo ocupado",
    11: "Gateway: dispositivo de destino no responde",
}


class ModbusError(Exception):
    pass


def _crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _build_request(function_code, start_address, quantity):
    frame = struct.pack(">BBHH", SLAVE_ID, function_code, start_address, quantity)
    return frame + struct.pack("<H", _crc16(frame))


def _open():
    return serial.Serial(
        port=PORT, baudrate=BAUDRATE, bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=TIMEOUT,
    )


def _check_header(ser, header, function_code):
    if header[1] & 0x80:
        rest = ser.read(3)
        if len(rest) < 3:
            raise ModbusError("Respuesta de excepcion incompleta.")
        code = rest[0]
        raise ModbusError(f"Excepcion Modbus: {_EXCEPTION_MESSAGES.get(code, f'codigo {code}')}")
    if header[1] != function_code:
        raise ModbusError(f"Funcion inesperada en la respuesta: {header[1]}")


def _verify_crc(frame, crc_bytes):
    expected = _crc16(frame)
    received = crc_bytes[0] | (crc_bytes[1] << 8)
    if expected != received:
        raise ModbusError("CRC invalido en la respuesta - ruido en el bus o baudrate incorrecto.")


def _read(function_code, start_address, quantity, expected_bytes):
    with _open() as ser:
        ser.reset_input_buffer()
        ser.write(_build_request(function_code, start_address, quantity))
        header = ser.read(2)
        if len(header) < 2:
            raise ModbusError("Sin respuesta del equipo (timeout) - normal para 01/02/04, ver docstring del modulo.")
        _check_header(ser, header, function_code)
        byte_count_raw = ser.read(1)
        payload = ser.read(expected_bytes)
        crc_bytes = ser.read(2)
        if len(byte_count_raw) < 1 or len(payload) < expected_bytes or len(crc_bytes) < 2:
            raise ModbusError("Respuesta incompleta (datos o CRC truncados).")
        _verify_crc(header + byte_count_raw + payload, crc_bytes)
        return payload, byte_count_raw[0]


def _read_bits(function_code, start_address, quantity):
    expected_bytes = (quantity + 7) // 8
    payload, byte_count = _read(function_code, start_address, quantity, expected_bytes)
    bits = []
    for byte in payload:
        for i in range(8):
            bits.append(bool((byte >> i) & 1))
    return bits[:quantity], byte_count, expected_bytes


def _read_registers(function_code, start_address, quantity):
    expected_bytes = quantity * 2
    payload, byte_count = _read(function_code, start_address, quantity, expected_bytes)
    return list(struct.unpack(f">{quantity}H", payload)), byte_count, expected_bytes


# clave -> (codigo de funcion, etiqueta tal como la nombra el manual del
# Carbomax Delta, es_bits). El orden define el orden en que se listan.
_FUNCTIONS = [
    ("coils", 1, "01 Read Coils", True),
    ("discrete_inputs", 2, "02 Read Discrete Input", True),
    ("holding_registers", 3, "03 Read Holding Registers", False),
    ("input_registers", 4, "04 Read Input Registers", False),
]


def leer_todo(start_address=0, quantity=32):
    """Corre las 4 funciones de lectura Modbus contra el equipo real y
    devuelve {clave: {label, start, quantity, ok, values | error, ...}}.
    Cada funcion es independiente: si una falla (excepcion, timeout, CRC)
    no aborta a las demas -- ver docstring del modulo para el antecedente
    de que hoy solo la 03 responde."""
    reg_quantity = max(1, min(int(quantity), MAX_REGISTER_QUANTITY))
    bit_quantity = max(1, min(int(quantity), MAX_BIT_QUANTITY))
    results = {}
    for key, func_code, label, is_bits in _FUNCTIONS:
        qty = bit_quantity if is_bits else reg_quantity
        entry = {"label": label, "start": start_address, "quantity": qty}
        try:
            if is_bits:
                values, byte_count, expected_bytes = _read_bits(func_code, start_address, qty)
                entry["values"] = [{"address": start_address + i, "value": int(v)} for i, v in enumerate(values)]
            else:
                values, byte_count, expected_bytes = _read_registers(func_code, start_address, qty)
                entry["values"] = [
                    {"address": start_address + i, "value": v, "hex": f"0x{v:04X}"}
                    for i, v in enumerate(values)
                ]
            entry["ok"] = True
            entry["byte_count_declarado"] = byte_count
            entry["byte_count_esperado"] = expected_bytes
        except Exception as ex:
            entry["ok"] = False
            entry["error"] = str(ex)
        results[key] = entry
    return results


# ---------------------------------------------------------------------------
# Lectura de produccion para carbomax_modbus_auto.py: un bloque de stand por
# vez, con reintentos (nadie va a reintentar a mano un loop de fondo sin
# operador presente), y el decodificador del layout CARBONO confirmado.

STAND_BLOCK_BASES = {3: 52, 4: 78}  # confirmado 11/09/2026, ver docstring del modulo
STAND_BLOCK_SIZE = 26  # registros reales del bloque; se lee de a 32 (tamano confiable)

READ_RETRIES = 2


def read_stand_block(base_address, retries=READ_RETRIES):
    """Lee los registros de un bloque de stand (32 registros desde
    base_address, tamano confiable -- ver nota de 32 vs 125 en el
    docstring del modulo) con reintentos. Devuelve la lista de 32 uint16."""
    last_error = None
    for _ in range(retries + 1):
        try:
            values, _byte_count, _expected_bytes = _read_registers(3, base_address, 32)
            return values
        except Exception as ex:
            last_error = ex
    raise ModbusError(f"bloque {base_address}: fallo tras {retries + 1} intentos: {last_error}")


def decode_carbono_block(registers, base_address):
    """registers: 32 uint16 leidos desde base_address (ver
    read_stand_block). Devuelve el resumen del modo CARBONO confirmado
    (ver docstring del modulo): unknown/tf/pico/tl/ce/ts/c/si, cada uno
    float o None si no hay registros suficientes."""

    def pair(offset):
        if offset + 1 >= len(registers):
            return None
        try:
            return struct.unpack(">f", struct.pack(">HH", registers[offset], registers[offset + 1]))[0]
        except (struct.error, OverflowError):
            return None

    return {
        "unknown": pair(2),
        "tf": pair(4),
        "pico": pair(6),
        "tl": pair(8),
        "ce": pair(10),
        "ts": pair(12),
        "c": pair(14),
        "si": pair(16),
    }
