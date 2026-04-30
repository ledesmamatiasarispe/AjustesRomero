// Macro simple para Fiji/ImageJ.
// Para cada imagen hace:
// 1. Smooth
// 2. Make Binary
// 3. Analyze Particles
// 4. Guarda Results como CSV con el nombre de la imagen
//
// Uso:
// - Ejecutar desde Fiji/ImageJ y elegir carpeta de entrada/salida
// - O por linea de comando:
//   ImageJ-win64.exe --headless --run imagej_batch_nodulos.ijm
//   "input=C:\\imagenes,output=C:\\salida,min=100,max=999999999,circ=0.00-1.00"

requires("1.53");
setBatchMode(true);

particleMinPx = 100;
particleMaxPx = 999999999;
circularityRange = "0.00-1.00";
saveMask = 0;

rawArgs = getArgument();
inputDir = parseArg(rawArgs, "input", "");
outputDir = parseArg(rawArgs, "output", "");
particleMinPx = parseFloatOrDefault(parseArg(rawArgs, "min", "" + particleMinPx), particleMinPx);
particleMaxPx = parseFloatOrDefault(parseArg(rawArgs, "max", "" + particleMaxPx), particleMaxPx);
circularityRange = parseArg(rawArgs, "circ", circularityRange);
saveMask = parseBoolArg(parseArg(rawArgs, "mask", "" + saveMask), saveMask);

if (inputDir == "") inputDir = getDirectory("Elegir carpeta de imagenes");
if (inputDir == "") exit("Cancelado.");

if (outputDir == "") outputDir = getDirectory("Elegir carpeta de salida");
if (outputDir == "") exit("Cancelado.");

inputDir = ensureTrailingSeparator(inputDir);
outputDir = ensureTrailingSeparator(outputDir);

resultsDir = outputDir + "csv" + File.separator;
maskDir = outputDir + "masks" + File.separator;
File.makeDirectory(resultsDir);
if (saveMask == 1) File.makeDirectory(maskDir);

sourceList = getFileList(inputDir);
processedImages = 0;
totalImages = 0;

for (i = 0; i < sourceList.length; i++) {
    if (isImageFile(toLowerCase(sourceList[i])) == 1) totalImages++;
}

if (totalImages == 0) exit("No se encontraron imagenes.");

logPath = outputDir + "macro_log.txt";
File.saveString("Macro ImageJ/Fiji\r\n", logPath);

for (i = 0; i < sourceList.length; i++) {
    name = sourceList[i];
    lower = toLowerCase(name);
    if (isImageFile(lower) == 0) continue;

    fullPath = inputDir + name;
    open(fullPath);
    originalTitle = getTitle();

    run("Duplicate...", "title=work");
    selectWindow("work");

    run("8-bit");
    run("Smooth");
    setAutoThreshold("Default dark");
    run("Make Binary");

    if (saveMask == 1) {
        saveAs("PNG", maskDir + stripExtension(name) + "_mask.png");
    }

    run("Set Measurements...", "area perimeter shape fit redirect=None decimal=4");
    run("Clear Results");
    run("Analyze Particles...", "size=" + particleMinPx + "-" + particleMaxPx + " circularity=" + circularityRange + " show=Nothing display clear");

    csvPath = resultsDir + stripExtension(name) + ".csv";
    writeResultsCsv(csvPath);
    run("Clear Results");

    if (isOpen("Summary")) {
        selectWindow("Summary");
        close();
    }

    selectWindow("work");
    close();
    selectWindow(originalTitle);
    close();

    processedImages++;
    File.append("OK: " + name + " -> " + csvPath + "\r\n", logPath);
}

setBatchMode(false);
showMessage("Macro finalizada", "Procesadas " + processedImages + " de " + totalImages + " imagenes.\nCSV: " + resultsDir);

function stripExtension(name) {
    dot = lastIndexOf(name, ".");
    if (dot < 0) return name;
    return substring(name, 0, dot);
}

function isImageFile(lowerName) {
    if (endsWith(lowerName, ".jpg")) return 1;
    if (endsWith(lowerName, ".jpeg")) return 1;
    if (endsWith(lowerName, ".png")) return 1;
    if (endsWith(lowerName, ".bmp")) return 1;
    if (endsWith(lowerName, ".tif")) return 1;
    if (endsWith(lowerName, ".tiff")) return 1;
    return 0;
}

function parseArg(source, key, defaultValue) {
    if (source == "") return defaultValue;
    parts = split(source, ",");
    for (j = 0; j < parts.length; j++) {
        entry = trim(parts[j]);
        if (startsWith(entry, key + "=")) {
            return trim(substring(entry, lengthOf(key) + 1));
        }
    }
    return defaultValue;
}

function parseBoolArg(value, defaultValue) {
    v = toLowerCase(trim(value));
    if (v == "1" || v == "true" || v == "si" || v == "yes") return 1;
    if (v == "0" || v == "false" || v == "no") return 0;
    return defaultValue;
}

function parseFloatOrDefault(value, defaultValue) {
    v = trim(value);
    if (v == "") return defaultValue;
    return parseFloat(v);
}

function ensureTrailingSeparator(path) {
    if (endsWith(path, "\\") || endsWith(path, "/")) return path;
    return path + File.separator;
}

function writeResultsCsv(csvPath) {
    header = "Area,Perim.,Circ.,AR,Round,Solidity\r\n";
    File.saveString(header, csvPath);
    rows = nResults;
    for (r = 0; r < rows; r++) {
        line = resultValue("Area", r) + "," +
            resultValue("Perim.", r) + "," +
            resultValue("Circ.", r) + "," +
            resultValue("AR", r) + "," +
            resultValue("Round", r) + "," +
            resultValue("Solidity", r) + "\r\n";
        File.append(line, csvPath);
    }
}

function resultValue(columnName, rowIndex) {
    value = getResult(columnName, rowIndex);
    if (isNaN(value)) return "";
    return "" + value;
}
