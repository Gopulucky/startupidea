import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "D:\\sih_drone_pipeline";
const SKILL_DIR = "C:\\Users\\gopuh\\.codex\\plugins\\cache\\openai-primary-runtime\\presentations\\26.905.11957\\skills\\presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-build", "visual_slide");
const FINAL_PPTX = path.join(workspaceDir, "deliverables", "SIH26158_Economic_Impact_One_Slide.pptx");
const RUNTIME_PYTHON = "C:\\Users\\gopuh\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";

const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const font = resolvePresentationFont({ fontFamily: "Arial" });

const C = {
  canvas: "#F7F9FC",
  navy: "#163A5F",
  ink: "#172636",
  muted: "#53687B",
  teal: "#0EA5A0",
  amber: "#D88412",
  line: "#D5DFE7",
  white: "#FFFFFF",
};

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const slide = presentation.slides.add();
slide.background.fill = C.canvas;

function rect(left, top, width, height, fill) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: "none", width: 0 },
  });
}

function text(value, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
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
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

text("Economic impact: usage and processing cost", 38, 24, 980, 46, {
  fontSize: 37, bold: true, color: C.ink, autoFit: "none",
});
text("SIH26158", 1090, 30, 150, 28, { fontSize: 18, bold: true, color: C.teal, alignment: "right", autoFit: "none" });
rect(38, 78, 1204, 2, C.line);

text("INDIA USAGE PROXY", 42, 101, 300, 24, { fontSize: 18, bold: true, color: C.navy, autoFit: "none" });
text("SVAMITVA villages with completed drone surveys", 42, 127, 590, 22, { fontSize: 15, color: C.muted, autoFit: "none" });
text("OUR VARIABLE COMPUTE COST", 792, 101, 410, 24, { fontSize: 18, bold: true, color: C.navy, autoFit: "none" });
text("Same GPU hourly rate, historical run = 100", 792, 127, 410, 22, { fontSize: 15, color: C.muted, autoFit: "none" });
rect(760, 96, 2, 440, C.line);

const usageChart = slide.charts.add("bar", {
  position: { left: 44, top: 158, width: 690, height: 360 },
  categories: ["2021", "2022", "2023", "2024", "2025"],
  series: [{
    name: "Villages surveyed, thousands",
    values: [90.504, 203.118, 289.0, 317.0, 328.0],
    fill: C.teal,
    valuesFormatCode: "0.0",
  }],
  barOptions: { direction: "column", grouping: "clustered", gapWidth: 42 },
  hasLegend: false,
  xAxis: {
    visible: true,
    textStyle: { fontSize: 12, fill: C.ink },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  yAxis: {
    visible: true, min: 0, max: 350, majorUnit: 50, numberFormatCode: "0",
    textStyle: { fontSize: 10, fill: C.muted },
    majorGridlines: { style: "solid", fill: C.line, width: 1 },
    line: { style: "solid", fill: C.line, width: 1 },
  },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 12, bold: true, fill: C.ink } },
  chartFill: C.canvas,
  chartLine: { style: "solid", fill: "none", width: 0 },
  plotAreaFill: C.canvas,
  plotAreaLine: { style: "solid", fill: "none", width: 0 },
});
applyPresentationChartFont(usageChart, { fontFamily: font });
text("Villages surveyed (thousands)", 42, 510, 690, 18, { fontSize: 12, bold: true, color: C.muted, alignment: "center", autoFit: "none" });

const costChart = slide.charts.add("bar", {
  position: { left: 786, top: 168, width: 430, height: 300 },
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
    textStyle: { fontSize: 10, fill: C.muted },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  yAxis: {
    visible: true,
    textStyle: { fontSize: 12, fill: C.ink },
    majorGridlines: null,
    line: { style: "solid", fill: C.line, width: 1 },
  },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 12, bold: true, fill: C.ink } },
  chartFill: C.canvas,
  chartLine: { style: "solid", fill: "none", width: 0 },
  plotAreaFill: C.canvas,
  plotAreaLine: { style: "solid", fill: "none", width: 0 },
});
applyPresentationChartFont(costChart, { fontFamily: font });
text("Variable cost per run (index)", 790, 469, 420, 18, { fontSize: 12, bold: true, color: C.muted, alignment: "center", autoFit: "none" });

rect(38, 548, 1204, 116, C.navy);
text("3.6×", 54, 567, 170, 45, { fontSize: 36, bold: true, color: C.white, autoFit: "none" });
text("usage growth since 2021", 54, 614, 260, 22, { fontSize: 15, color: "#D9E6F0", autoFit: "none" });
rect(370, 566, 2, 76, "#496986");
text("₹566.23 cr", 412, 567, 220, 45, { fontSize: 32, bold: true, color: C.white, autoFit: "none" });
text("SVAMITVA programme cost", 412, 614, 270, 22, { fontSize: 15, color: "#D9E6F0", autoFit: "none" });
rect(760, 566, 2, 76, "#496986");
text("81% lower", 804, 567, 220, 45, { fontSize: 34, bold: true, color: "#6FE1D7", autoFit: "none" });
text("GPU time in rapid mode", 804, 614, 300, 22, { fontSize: 15, color: "#D9E6F0", autoFit: "none" });

text("Usage data: Government of India, Dec year-end values. Cost index assumes usage-based GPU billing and excludes capture, labour and software licensing.", 42, 682, 1190, 16, {
  fontSize: 11, color: C.muted, autoFit: "none",
});

slide.speakerNotes.textFrame.setText([
  "Usage proxy: cumulative villages where drone flying was completed under India's SVAMITVA programme.",
  "2021, 90,504 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=1786259",
  "2022, 203,118 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=1885885",
  "2023, 289,000 villages: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=1991702",
  "2024, 317,000 villages: https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2090152",
  "2025, 328,000 villages: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2209532",
  "SVAMITVA programme cost of ₹566.23 crore through FY 2025-26: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/apr/doc2025423544601.pdf",
  "Compute-cost index: historical 80.75 minutes = 100. Full run = 28.81 / 80.75 × 100 = 35.7. Rapid run = 15 / 80.75 × 100 = 18.6.",
  "The cost index assumes the same usage-based GPU hourly rate. It does not estimate capture, labour, storage, software licensing or hardware depreciation.",
]);

const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "SIH26158_Economic_Impact_One_Slide_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

await finalizePresentation({
  explicitTotalSlideCount: 1,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [1],
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
  receiptPath: path.join(stagingDir, "SIH26158_Economic_Impact_One_Slide.validation.json"),
});

console.log(FINAL_PPTX);
