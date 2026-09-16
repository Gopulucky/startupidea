import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "D:\\sih_drone_pipeline";
const SKILL_DIR = "C:\\Users\\gopuh\\.codex\\plugins\\cache\\openai-primary-runtime\\presentations\\26.905.11957\\skills\\presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-build", "visual_slide");
const FINAL_PPTX = path.join(workspaceDir, "deliverables", "SIH26158_Feasibility_Impact_Economic_2_Slides_Final_v2.pptx");
const RUNTIME_PYTHON = "C:\\Users\\gopuh\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";

const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const font = resolvePresentationFont({ fontFamily: "Arial" });

const assets = {
  capture: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c5_o1.png"),
  dsm: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c8_o0.png"),
  geometry: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c7_o3.png"),
  flight: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab_c5_o0.png"),
  optimizedDsm: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Optimization_1088_Colab_c9_o0.png"),
};
const bytes = Object.fromEntries(await Promise.all(
  Object.entries(assets).map(async ([key, file]) => [key, await fs.readFile(file)]),
));

const C = {
  white: "#FFFFFF",
  canvas: "#F7F9FC",
  navy: "#163A5F",
  ink: "#172636",
  muted: "#53687B",
  blue: "#176AA9",
  teal: "#0EA5A0",
  green: "#14845C",
  amber: "#D88412",
  red: "#C84646",
  paleBlue: "#EAF3FA",
  paleGreen: "#EAF6F1",
  paleAmber: "#FFF4DF",
  line: "#D5DFE7",
};

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
let slide = presentation.slides.add();
slide.background.fill = C.canvas;

function rect(left, top, width, height, fill, lineFill = "none", lineWidth = 0) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
  });
}

function text(value, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height, ...(options.rotation !== undefined ? { rotation: options.rotation } : {}) },
    fill: options.fill ?? "none",
    line: { style: "solid", fill: options.lineFill ?? "none", width: options.lineWidth ?? 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: font,
    fontSize: options.fontSize ?? 22,
    bold: options.bold ?? false,
    color: options.color ?? C.ink,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    autoFit: options.autoFit ?? "shrinkText",
    insets: options.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function sectionLabel(number, label, left, top) {
  text(number, left, top, 35, 25, { fontSize: 15, bold: true, color: C.teal, autoFit: "none" });
  text(label, left + 36, top - 2, 300, 29, { fontSize: 21, bold: true, color: C.navy, autoFit: "none" });
}

// Header
text("Feasibility proof from completed drone-video runs", 38, 24, 970, 46, {
  fontSize: 37, bold: true, color: C.ink, autoFit: "none",
});
text("SIH26158", 1090, 30, 150, 28, { fontSize: 18, bold: true, color: C.teal, alignment: "right", autoFit: "none" });
rect(38, 78, 1204, 2, C.line);

// Quadrant separators inspired by the supplied reference.
rect(632, 96, 2, 554, "#CF7777");
rect(38, 367, 1204, 2, "#CF7777");

// 1. Input evidence
sectionLabel("01", "INPUT CAPTURE", 44, 100);
slide.images.add({
  blob: bytes.capture,
  contentType: "image/png",
  alt: "Frames sampled throughout the continuous drone flight",
  fit: "cover",
  crop: { left: 0, top: 0.15, right: 0, bottom: 0.16 },
  position: { left: 44, top: 136, width: 565, height: 184 },
});
rect(44, 320, 565, 34, C.navy);
text("4.19-minute flight     253 keyframes     2,525 telemetry samples", 57, 328, 540, 18, {
  fontSize: 15, bold: true, color: C.white, alignment: "center", autoFit: "none",
});

// 2. GIS and 3D output evidence
sectionLabel("02", "OUTPUT PRODUCTS", 655, 100);
slide.images.add({
  blob: bytes.dsm,
  contentType: "image/png",
  alt: "Exported digital surface model in EPSG 32610",
  fit: "contain",
  position: { left: 655, top: 135, width: 280, height: 216 },
});
text("604,982", 956, 142, 245, 50, { fontSize: 39, bold: true, color: C.blue, autoFit: "none" });
text("COLOURED POINTS", 958, 194, 220, 21, { fontSize: 14, bold: true, color: C.muted, autoFit: "none" });
text("361,510", 956, 225, 245, 42, { fontSize: 31, bold: true, color: C.ink, autoFit: "none" });
text("MESH FACES", 958, 267, 200, 20, { fontSize: 14, bold: true, color: C.muted, autoFit: "none" });
text("GLB, LAS and GeoTIFF", 956, 304, 250, 25, { fontSize: 18, bold: true, color: C.green, autoFit: "none" });
text("EPSG:32610    DSM 0.5 m", 956, 331, 250, 19, { fontSize: 15, color: C.muted, autoFit: "none" });

// 3. Runtime evidence as an editable native chart
sectionLabel("03", "RUNTIME PROOF", 44, 390);
const chart = slide.charts.add("bar", {
  position: { left: 38, top: 426, width: 428, height: 212 },
  categories: ["Historical", "253 frames", "Reduced frames"],
  series: [{
    name: "Minutes",
    values: [80.75, 28.81, 15.00],
    fill: "#94B9D3",
    points: [
      { idx: 0, fill: "#A9C4D7" },
      { idx: 1, fill: C.teal },
      { idx: 2, fill: C.amber },
    ],
    valuesFormatCode: "0.00",
  }],
  barOptions: { direction: "bar", grouping: "clustered", gapWidth: 45 },
  hasLegend: false,
  xAxis: {
    visible: true, min: 0, max: 90, majorUnit: 30, numberFormatCode: "0", tickLabelPosition: "nextTo",
    textStyle: { fontSize: 10, fill: C.muted },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  yAxis: {
    visible: true,
    tickLabelPosition: "nextTo",
    textStyle: { fontSize: 11, fill: C.ink },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 13, bold: true, fill: C.ink } },
  chartFill: C.canvas,
  chartLine: { style: "solid", fill: "none", width: 0 },
  plotAreaFill: C.canvas,
  plotAreaLine: { style: "solid", fill: "none", width: 0 },
});
applyPresentationChartFont(chart, { fontFamily: font });
text("Processing mode", 0, 480, 100, 16, {
  fontSize: 11, bold: true, color: C.muted, alignment: "center", verticalAlignment: "middle", rotation: 270, autoFit: "none",
});
text("Runtime (minutes)", 202, 625, 190, 17, {
  fontSize: 11, bold: true, color: C.muted, alignment: "center", autoFit: "none",
});
text("15 min", 478, 438, 132, 48, { fontSize: 36, bold: true, color: C.teal, alignment: "center", autoFit: "none" });
text("reduced frames", 478, 490, 132, 20, { fontSize: 15, bold: true, color: C.muted, alignment: "center", autoFit: "none" });
text("target achieved", 478, 512, 132, 18, { fontSize: 13, bold: true, color: C.green, alignment: "center", autoFit: "none" });
text("28.81 min", 478, 558, 132, 31, { fontSize: 24, bold: true, color: C.ink, alignment: "center", autoFit: "none" });
text("all 253 frames", 485, 591, 118, 21, { fontSize: 14, color: C.muted, alignment: "center", autoFit: "none" });

// 4. Reconstruction evidence
sectionLabel("04", "QUALITY EVIDENCE", 655, 390);
slide.images.add({
  blob: bytes.geometry,
  contentType: "image/png",
  alt: "Geometry diagnostics from the controlled 253-frame experiment",
  fit: "contain",
  position: { left: 650, top: 427, width: 400, height: 206 },
});
text("PASS", 1072, 434, 150, 31, { fontSize: 24, bold: true, color: C.green, alignment: "center", autoFit: "none" });
text("capture screen", 1072, 465, 150, 20, { fontSize: 14, color: C.muted, alignment: "center", autoFit: "none" });
text("0.458 px", 1072, 505, 150, 31, { fontSize: 24, bold: true, color: C.blue, alignment: "center", autoFit: "none" });
text("reprojection", 1072, 536, 150, 20, { fontSize: 14, color: C.muted, alignment: "center", autoFit: "none" });
text("81.82%", 1072, 576, 150, 31, { fontSize: 24, bold: true, color: C.red, alignment: "center", autoFit: "none" });
text("registered", 1072, 607, 150, 20, { fontSize: 14, color: C.muted, alignment: "center", autoFit: "none" });

// Evidence boundary
rect(38, 660, 1204, 42, C.paleAmber);
text("Accuracy proof pending", 52, 671, 230, 20, { fontSize: 17, bold: true, color: C.amber, autoFit: "none" });
text("Independent checkpoint RMSE has not been evaluated. GPS camera RMSE cannot prove the one-metre surface target.", 282, 671, 944, 20, {
  fontSize: 16, color: C.ink, autoFit: "none",
});

slide.speakerNotes.textFrame.setText([
  "Sources: optimized_v1/run_report.json; optimized_v1/verification_report.json; optimized_v1/preflight.json; optimized_v1/capture_quality.json.",
  "Input image: SIH26158_HF_Drone_Full253_AB_Colab (1).ipynb, cell 5.",
  "DSM image: the same notebook, cell 8. Geometry diagnostics: the same notebook, cell 7.",
  "Runtime evidence: the archived run_report.json records 28.81 minutes for all 253 frames. The project team reports a 15-minute run after reducing the processed frame count. Historical baseline: 80.75 minutes.",
  "The archive reports no surveyed checkpoints or independent reference surface, so the one-metre surface target remains unevaluated.",
]);

// Slide 2: combined target-user impact, strategic value and economic evidence.
slide = presentation.slides.add();
slide.background.fill = C.canvas;

text("Impact, benefits and economics", 38, 24, 900, 46, {
  fontSize: 37, bold: true, color: C.ink, autoFit: "none",
});
text("SIH26158", 1090, 30, 150, 28, { fontSize: 18, bold: true, color: C.teal, alignment: "right", autoFit: "none" });
rect(38, 78, 1204, 2, C.line);
rect(510, 96, 2, 564, "#CF7777");

function compactImpact(top, heading, body, accent = C.blue) {
  text(heading, 50, top, 430, 20, { fontSize: 16, bold: true, color: accent, autoFit: "none" });
  text(body, 50, top + 21, 430, 22, { fontSize: 14, color: C.ink, autoFit: "none" });
}

text("DIRECT IMPACT ON TARGET USERS", 42, 102, 440, 24, {
  fontSize: 19, bold: true, color: C.navy, autoFit: "none",
});
compactImpact(136, "Survey and GIS teams", "3D model + DSM from one drone flight.");
compactImpact(180, "Infrastructure teams", "Inspect difficult terrain before field deployment.");
compactImpact(224, "Emergency response teams", "15-minute rapid site assessment.");

text("ECONOMIC & OPERATIONAL BENEFITS", 42, 283, 440, 24, {
  fontSize: 19, bold: true, color: C.navy, autoFit: "none",
});
compactImpact(317, "Lower survey overhead", "Reuse existing drone video and telemetry.", C.green);
compactImpact(361, "Faster turnaround", "15 min rapid / 28.81 min full-detail run.", C.green);
compactImpact(405, "Portable outputs", "GLB, LAS and GeoTIFF avoid tool lock-in.", C.green);

text("STRATEGIC IMPACT", 42, 464, 440, 24, {
  fontSize: 19, bold: true, color: C.navy, autoFit: "none",
});
compactImpact(498, "Local geospatial capability", "Open pipeline, reports and standard outputs.", C.teal);
compactImpact(542, "Shared operational picture", "GIS, 3D and browser-ready mission data.", C.teal);
compactImpact(586, "Scales with each mission", "Choose rapid mode or full 253-frame detail.", C.teal);

text("5-YEAR USAGE SIGNAL", 540, 102, 300, 22, { fontSize: 18, bold: true, color: C.navy, autoFit: "none" });
text("SVAMITVA villages surveyed (thousands)", 540, 126, 455, 19, { fontSize: 13, color: C.muted, autoFit: "none" });

const usageChart = slide.charts.add("bar", {
  position: { left: 540, top: 151, width: 455, height: 211 },
  categories: ["2021", "2022", "2023", "2024", "2025"],
  series: [{
    name: "Villages surveyed, thousands",
    values: [90.504, 203.118, 289.0, 317.0, 328.0],
    fill: C.teal,
    valuesFormatCode: "0.0",
  }],
  barOptions: { direction: "column", grouping: "clustered", gapWidth: 38 },
  hasLegend: false,
  xAxis: {
    visible: true,
    textStyle: { fontSize: 10, fill: C.ink },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  yAxis: {
    visible: true, min: 0, max: 350, majorUnit: 50, numberFormatCode: "0",
    textStyle: { fontSize: 9, fill: C.muted },
    majorGridlines: { style: "solid", fill: C.line, width: 1 },
    line: { style: "solid", fill: C.line, width: 1 },
  },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 10, bold: true, fill: C.ink } },
  chartFill: C.canvas,
  chartLine: { style: "solid", fill: "none", width: 0 },
  plotAreaFill: C.canvas,
  plotAreaLine: { style: "solid", fill: "none", width: 0 },
});
applyPresentationChartFont(usageChart, { fontFamily: font });

rect(1015, 153, 195, 91, C.paleTeal);
text("3.6×", 1030, 164, 165, 36, { fontSize: 30, bold: true, color: C.teal, alignment: "center", autoFit: "none" });
text("usage since 2021", 1030, 204, 165, 20, { fontSize: 13, color: C.ink, alignment: "center", autoFit: "none" });
rect(1015, 263, 195, 91, C.paleAmber);
text("₹566.23 cr", 1025, 277, 175, 30, { fontSize: 24, bold: true, color: C.amber, alignment: "center", autoFit: "none" });
text("programme scale", 1030, 315, 165, 20, { fontSize: 13, color: C.ink, alignment: "center", autoFit: "none" });

text("OUR PROCESSING-COST CHANGE", 540, 388, 390, 22, { fontSize: 18, bold: true, color: C.navy, autoFit: "none" });
text("Variable GPU cost index · historical run = 100", 540, 412, 455, 19, { fontSize: 13, color: C.muted, autoFit: "none" });

const costChart = slide.charts.add("bar", {
  position: { left: 540, top: 435, width: 455, height: 205 },
  categories: ["Historical", "Our full", "Our rapid"],
  series: [{
    name: "Compute-cost index",
    values: [100.0, 35.7, 18.6],
    fill: "#A9C4D7",
    points: [
      { idx: 0, fill: "#A9C4D7" },
      { idx: 1, fill: C.teal },
      { idx: 2, fill: C.amber },
    ],
    valuesFormatCode: "0.0",
  }],
  barOptions: { direction: "bar", grouping: "clustered", gapWidth: 45 },
  hasLegend: false,
  xAxis: {
    visible: true, min: 0, max: 110, majorUnit: 25, numberFormatCode: "0",
    textStyle: { fontSize: 9, fill: C.muted },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  yAxis: {
    visible: true,
    textStyle: { fontSize: 11, fill: C.ink },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 10, bold: true, fill: C.ink } },
  chartFill: C.canvas,
  chartLine: { style: "solid", fill: "none", width: 0 },
  plotAreaFill: C.canvas,
  plotAreaLine: { style: "solid", fill: "none", width: 0 },
});
applyPresentationChartFont(costChart, { fontFamily: font });

rect(1015, 440, 195, 190, C.navy);
text("81%", 1030, 465, 165, 48, { fontSize: 40, bold: true, color: "#6FE1D7", alignment: "center", autoFit: "none" });
text("lower GPU time", 1030, 516, 165, 22, { fontSize: 16, bold: true, color: C.white, alignment: "center", autoFit: "none" });
text("15 min rapid mode\nvs 80.75 min historical", 1030, 552, 165, 48, { fontSize: 13, color: "#D9E6F0", alignment: "center", autoFit: "none" });

text("Usage proxy: Government of India SVAMITVA data. Cost index assumes the same usage-based GPU rate; capture, labour and licensing excluded.", 42, 681, 1188, 16, {
  fontSize: 10.5, color: C.muted, autoFit: "none",
});

slide.speakerNotes.textFrame.setText([
  "Target-user and impact statements describe intended operational use; they are not measured deployment outcomes.",
  "The archived run_report.json records 28.81 minutes for all 253 frames. The project team reports a 15-minute run after reducing the processed frame count.",
  "Usage proxy: cumulative villages where drone flying was completed under India's SVAMITVA programme.",
  "2021, 90,504 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=1786259",
  "2022, 203,118 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=1885885",
  "2023, 289,000 villages: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=1991702",
  "2024, 317,000 villages: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2090152",
  "2025, 328,000 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2209532",
  "SVAMITVA programme cost of ₹566.23 crore through FY 2025-26: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/apr/doc2025423544601.pdf",
  "Compute-cost index calculation: historical 80.75 minutes = 100. Full run = 28.81 / 80.75 × 100 = 35.7. Rapid run = 15 / 80.75 × 100 = 18.6.",
  "The cost index assumes the same usage-based GPU hourly rate. It does not estimate capture, labour, storage, software licensing or hardware depreciation.",
]);

const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "SIH26158_Feasibility_Impact_Economic_2_Slides_Final_v2_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

await finalizePresentation({
  explicitTotalSlideCount: 2,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [1, 2],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  fontPolicy: { basis: "design", families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "SIH26158_Feasibility_Impact_Economic_2_Slides_Final_v2.validation.json"),
});

console.log(FINAL_PPTX);

