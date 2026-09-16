import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "D:\\sih_drone_pipeline";
const SKILL_DIR = "C:\\Users\\gopuh\\.codex\\plugins\\cache\\openai-primary-runtime\\presentations\\26.905.11957\\skills\\presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-build", "presentation");
const FINAL_PPTX = path.join(workspaceDir, "deliverables", "SIH26158_Feasibility_Evidence_Core.pptx");
const RUNTIME_PYTHON = "C:\\Users\\gopuh\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";

const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

const font = resolvePresentationFont({ fontFamily: "Arial" });
const mono = "Courier New";
const W = 1280;
const H = 720;

const C = {
  navy: "#071A2B",
  ink: "#132536",
  muted: "#526578",
  blue: "#1769AA",
  cyan: "#1BA6A6",
  green: "#11865B",
  amber: "#D88516",
  red: "#C54747",
  paleBlue: "#EAF3FA",
  paleGreen: "#E9F6F0",
  paleAmber: "#FFF4DF",
  paleRed: "#FBECEC",
  line: "#D7E0E7",
  white: "#FFFFFF",
  offWhite: "#F7F9FB",
};

function addRect(slide, left, top, width, height, fill, lineFill = "none", lineWidth = 0) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
  });
}

function addText(slide, text, left, top, width, height, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: opts.fill ?? "none",
    line: { style: "solid", fill: opts.lineFill ?? "none", width: opts.lineWidth ?? 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: opts.typeface ?? font,
    fontSize: opts.fontSize ?? 24,
    bold: opts.bold ?? false,
    color: opts.color ?? C.ink,
    alignment: opts.alignment ?? "left",
    autoFit: opts.autoFit ?? "shrinkText",
    italic: opts.italic ?? false,
  };
  return shape;
}

function addTitle(slide, title, number) {
  addText(slide, title, 64, 42, 1080, 58, { fontSize: 41, bold: true, color: C.ink });
  addRect(slide, 64, 111, 72, 5, C.cyan);
  addText(slide, String(number).padStart(2, "0"), 1170, 50, 52, 28, {
    fontSize: 17, bold: true, color: C.muted, alignment: "right",
  });
}

function addFooter(slide, source) {
  addRect(slide, 64, 678, 1152, 1, C.line);
  addText(slide, source, 64, 687, 1152, 20, { fontSize: 12, color: C.muted, autoFit: "none" });
}

function addStatusRow(slide, y, label, value, status, detail, color, pale) {
  addText(slide, label, 790, y, 190, 30, { fontSize: 18, bold: true, color: C.ink });
  addText(slide, value, 982, y, 218, 30, { fontSize: 18, bold: true, color, alignment: "right" });
  addText(slide, status, 790, y + 34, 410, 30, { fontSize: 15, bold: true, color, fill: pale });
  addText(slide, detail, 790, y + 68, 410, 47, { fontSize: 15, color: C.muted });
}

const images = {
  contact: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c5_o1.png"),
  telemetry: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c5_o0.png"),
  dsm: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c8_o0.png"),
  geometry: path.join(workspaceDir, ".codex-build", "notebook_images", "SIH26158_HF_Drone_Full253_AB_Colab__1__c7_o3.png"),
};
const imageBytes = Object.fromEntries(await Promise.all(
  Object.entries(images).map(async ([key, value]) => [key, await fs.readFile(value)]),
));

const presentation = Presentation.create({ slideSize: { width: W, height: H } });

// Slide 1
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  slide.images.add({
    blob: imageBytes.contact,
    contentType: "image/png",
    alt: "Twelve frames sampled across the 4.2-minute drone flight",
    fit: "cover",
    position: { left: 650, top: 0, width: 630, height: 720 },
    crop: { left: 0.02, top: 0.05, right: 0.02, bottom: 0.06 },
  });
  addRect(slide, 0, 0, 650, 720, C.navy);
  addText(slide, "SIH26158", 68, 78, 470, 40, { fontSize: 22, bold: true, color: C.cyan });
  addText(slide, "Feasibility\nevidence", 68, 142, 520, 190, {
    fontSize: 62, bold: true, color: C.white, autoFit: "none",
  });
  addText(slide, "Single-pass drone video to georeferenced 3D and GIS products", 68, 358, 500, 82, {
    fontSize: 25, color: "#C9D6E2",
  });
  addRect(slide, 68, 474, 96, 6, C.cyan);
  addText(slide, "Verified run: 4.2-minute video, 253 selected frames, CUDA on Tesla T4", 68, 505, 500, 82, {
    fontSize: 20, color: C.white,
  });
  addText(slide, "Evidence date 14 September 2026", 68, 651, 420, 24, { fontSize: 14, color: "#8FA4B7" });
  slide.speakerNotes.textFrame.setText([
    "Open with the evidence boundary: the repository demonstrates end-to-end technical feasibility.",
    "Do not claim the 15-minute target or one-metre surface accuracy from this archived run.",
    "Source image: SIH26158_HF_Drone_Full253_AB_Colab (1).ipynb, cell 5 output.",
  ]);
}

// Slide 2
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "One continuous flight produced a reproducible metric input set", 2);
  slide.images.add({
    blob: imageBytes.telemetry,
    contentType: "image/png",
    alt: "GPS flight path and altitude telemetry across the video",
    fit: "contain",
    position: { left: 64, top: 154, width: 700, height: 292 },
  });
  addText(slide, "4.19 min", 814, 152, 360, 60, { fontSize: 42, bold: true, color: C.blue });
  addText(slide, "video duration", 816, 211, 300, 30, { fontSize: 17, color: C.muted });
  addText(slide, "7,538", 814, 270, 360, 60, { fontSize: 42, bold: true, color: C.blue });
  addText(slide, "source frames at 1920 x 1080", 816, 329, 340, 30, { fontSize: 17, color: C.muted });
  addText(slide, "2,525", 814, 388, 360, 60, { fontSize: 42, bold: true, color: C.blue });
  addText(slide, "telemetry samples covering the video", 816, 447, 360, 30, { fontSize: 17, color: C.muted });
  addRect(slide, 64, 488, 1152, 1, C.line);
  addText(slide, "253 geometry-aware keyframes", 64, 518, 350, 34, { fontSize: 24, bold: true, color: C.ink });
  addText(slide, "Selected at about 1 frame per second with 5.73 m median GPS baseline and 97.5% median tracked features.", 64, 558, 500, 68, { fontSize: 18, color: C.muted });
  addText(slide, "Preflight ready", 665, 518, 270, 34, { fontSize: 24, bold: true, color: C.green });
  addText(slide, "COLMAP 4.2 with CUDA, NVIDIA T4 visible, telemetry valid, no timestamp reversals, gaps, or probable position jumps.", 665, 558, 500, 68, { fontSize: 18, color: C.muted });
  addFooter(slide, "Sources: input_summary.json, preflight.json, frames.selection.json");
  slide.speakerNotes.textFrame.setText([
    "This slide proves that the reconstruction used one continuous video with synchronized telemetry.",
    "The telemetry plot and flight frames come from the controlled full-253-frame experiment notebook.",
    "Sources: SIH26158/evidence_20260914_080536/input_summary.json; preflight.json; frames.selection.json.",
  ]);
}

// Slide 3
{
  const slide = presentation.slides.add();
  slide.background.fill = C.offWhite;
  addTitle(slide, "The completed run exported valid 3D and GIS products", 3);
  slide.images.add({
    blob: imageBytes.dsm,
    contentType: "image/png",
    alt: "Digital surface model exported from the reconstructed point cloud",
    fit: "contain",
    position: { left: 728, top: 132, width: 480, height: 518 },
  });
  addText(slide, "604,982", 70, 150, 340, 56, { fontSize: 46, bold: true, color: C.blue });
  addText(slide, "filtered coloured points", 72, 207, 330, 28, { fontSize: 18, color: C.muted });
  addText(slide, "181,314 vertices", 70, 267, 360, 36, { fontSize: 28, bold: true, color: C.ink });
  addText(slide, "361,510 faces across 3 retained components", 72, 309, 480, 34, { fontSize: 18, color: C.muted });
  addRect(slide, 70, 369, 565, 1, C.line);
  addText(slide, "Verified deliverables", 70, 394, 340, 34, { fontSize: 23, bold: true, color: C.ink });
  addText(slide, "model.glb     valid, textured, 1 mesh\npoint_cloud.las     valid, EPSG:32610\ndsm.tif     valid, EPSG:32610, 0.5 m pixels\nmodel.obj and mesh.ply     present and valid", 72, 439, 570, 145, {
    fontSize: 18, color: C.ink, typeface: mono,
  });
  addText(slide, "The DSM contains 111,476 valid cells. Its 13.84% coverage misses the current 75% production gate, so present it as output proof rather than complete-site coverage.", 70, 599, 585, 58, { fontSize: 16, color: C.red });
  addFooter(slide, "Sources: verification_report.json and run_report.json; DSM image from Full253 notebook output");
  slide.speakerNotes.textFrame.setText([
    "Use the DSM image as visible evidence that the pipeline exported a georeferenced raster.",
    "The verification report validates the GLB header and JSON chunk, LAS point count and CRS, GeoTIFF dimensions and CRS, and mesh structure.",
    "Source: SIH26158/evidence_20260914_080536/verification_report.json and run_report.json.",
  ]);
}

// Slide 4
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "Runtime optimization versus the 15-minute target", 4);
  const categories = ["15-minute target", "Latest archived run", "Frontend optimization", "Geometry fast", "Controlled baseline", "Historical run"];
  const values = [15.00, 28.81, 34.62, 52.62, 78.07, 80.75];
  const chart = slide.charts.add("bar", {
    position: { left: 74, top: 142, width: 790, height: 468 },
    categories,
    series: [{
      name: "Runtime (minutes)",
      values,
      fill: C.blue,
      points: [
        { idx: 0, fill: C.amber },
        { idx: 1, fill: C.cyan },
        { idx: 2, fill: "#4A8FC5" },
        { idx: 3, fill: "#6FA6CF" },
        { idx: 4, fill: "#9BBFD9" },
        { idx: 5, fill: "#B7CCDB" },
      ],
      valuesFormatCode: "0.00",
    }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 42 },
    hasLegend: false,
    xAxis: {
      visible: true, min: 0, max: 90, majorUnit: 15, numberFormatCode: "0",
      title: { text: "Minutes", textStyle: { fontSize: 16, fill: C.muted } },
      textStyle: { fontSize: 14, fill: C.muted },
      majorGridlines: { style: "solid", fill: C.line, width: 1 },
      line: { style: "solid", fill: C.line, width: 1 },
    },
    yAxis: {
      visible: true,
      textStyle: { fontSize: 15, fill: C.ink },
      line: { style: "solid", fill: C.line, width: 1 },
      majorGridlines: null,
    },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 15, fill: C.ink, bold: true } },
    chartFill: C.white,
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaFill: C.white,
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  applyPresentationChartFont(chart, { fontFamily: font });
  addText(slide, "2.80x", 912, 169, 270, 64, { fontSize: 48, bold: true, color: C.cyan });
  addText(slide, "speedup versus the 80.75-minute historical run", 914, 235, 282, 62, { fontSize: 18, color: C.muted });
  addText(slide, "28.81 min", 912, 340, 270, 52, { fontSize: 38, bold: true, color: C.ink });
  addText(slide, "latest archived wall-clock result", 914, 398, 280, 44, { fontSize: 18, color: C.muted });
  addText(slide, "A further 47.9% reduction, or 1.92x speedup, is required to reach 15 minutes on this measured result.", 912, 492, 282, 102, { fontSize: 19, color: C.red });
  addFooter(slide, "Sources: Full253 and Frontend Sparse A/B notebook outputs; evidence run_report.json");
  slide.speakerNotes.textFrame.setText([
    "The bars combine documented experiment outputs and the latest archived evidence run.",
    "Do not imply that every historical bar is an identical configuration. Use the chart as optimization history.",
    "The latest evidence package reports 1,728.47 seconds wall clock and 1,522.40 seconds across reconstruction stages.",
    "Sources: SIH26158_HF_Drone_Full253_AB_Colab (1).ipynb cell 7; SIH26158_HF_Drone_Frontend_Sparse_AB_Colab.ipynb cell 17; SIH26158/evidence_20260914_080536/run_report.json.",
  ]);
}

// Slide 5
{
  const slide = presentation.slides.add();
  slide.background.fill = C.offWhite;
  addTitle(slide, "Capture checks passed, while reconstruction quality remains mixed", 5);
  slide.images.add({
    blob: imageBytes.geometry,
    contentType: "image/png",
    alt: "Geometry diagnostics comparing uniform and geometry-aware keyframe selection",
    fit: "contain",
    position: { left: 54, top: 147, width: 700, height: 450 },
  });
  addStatusRow(slide, 150, "Capture screen", "READY", "Passed all configured capture gates", "0% blurred, 0% poor exposure, no telemetry gaps", C.green, C.paleGreen);
  addStatusRow(slide, 285, "Reprojection", "0.458 px", "PASS against the 2 px gate", "Sparse model geometry is internally consistent", C.green, C.paleGreen);
  addStatusRow(slide, 420, "Registration", "81.82%", "FAIL against the 90% gate", "207 of 253 selected images registered", C.red, C.paleRed);
  addStatusRow(slide, 555, "AI masking", "SKIPPED", "Capability exists but this run did not test it", "A masked versus unmasked proof image still needs a rerun", C.amber, C.paleAmber);
  addFooter(slide, "Sources: run_report.json, verification_report.json, reusable_run_assessment.json");
  slide.speakerNotes.textFrame.setText([
    "The capture-quality gate is a risk screen, not an accuracy certificate.",
    "Geometry-aware selection improved the median baseline and parallax in the controlled comparison, but the archived run registered only 81.82% of selected images.",
    "Dynamic masking code exists in the repository. The evidence run explicitly records ai_dynamic_masking as skipped.",
  ]);
}

// Slide 6
{
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addTitle(slide, "One-metre surface accuracy remains unevaluated", 6);
  addText(slide, "1.835 m", 70, 164, 460, 80, { fontSize: 64, bold: true, color: C.amber });
  addText(slide, "GPS camera-alignment RMSE", 72, 248, 460, 34, { fontSize: 22, bold: true, color: C.ink });
  addText(slide, "Diagnostic only. It compares reconstructed camera positions with flight GPS. It does not measure surface accuracy.", 72, 294, 490, 92, { fontSize: 19, color: C.muted });
  addRect(slide, 70, 420, 485, 1, C.line);
  addText(slide, "Checkpoint RMSE", 72, 452, 300, 34, { fontSize: 22, bold: true, color: C.ink });
  addText(slide, "NOT EVALUATED", 72, 495, 420, 58, { fontSize: 38, bold: true, color: C.red });
  addText(slide, "No independent checkpoint set or reference surface is included in the evidence bundle.", 72, 560, 490, 60, { fontSize: 18, color: C.muted });
  addRect(slide, 624, 150, 1, 484, C.line);
  addText(slide, "Evidence required for the final claim", 678, 160, 490, 42, { fontSize: 27, bold: true, color: C.ink });
  const steps = [
    ["01", "Survey holdout points", "Use at least three independent checkpoints for the project gate. Thirty points only satisfies the repository's checkpoint-count status."],
    ["02", "Measure them in the reconstruction", "Record reconstructed and surveyed XYZ in checkpoint_measurements.csv."],
    ["03", "Run the existing validator", "python -m sih_drone_pipeline validate-checkpoints --output <run> --checkpoints <csv>"],
    ["04", "Show the numerical result", "Present checkpoint 3D RMSE below 1.0 m, with the CSV and report retained as evidence."],
  ];
  let y = 224;
  for (const [n, head, body] of steps) {
    addText(slide, n, 680, y, 52, 34, { fontSize: 18, bold: true, color: C.cyan });
    addText(slide, head, 742, y, 438, 31, { fontSize: 20, bold: true, color: C.ink });
    addText(slide, body, 742, y + 34, 438, 57, { fontSize: 16, color: C.muted, typeface: head === "Run the existing validator" ? mono : font });
    y += 102;
  }
  addFooter(slide, "Sources: verification_report.json and README accuracy-evidence protocol");
  slide.speakerNotes.textFrame.setText([
    "This is the most important credibility slide.",
    "The report leaves one_metre_accuracy and checkpoint_rmse_3d_m null. State that directly.",
    "The repository already implements the required validator. The missing work is independent field evidence, not software plumbing.",
  ]);
}

// Slide 7
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  addText(slide, "Final judging evidence pack", 64, 50, 920, 58, { fontSize: 43, bold: true, color: C.white });
  addText(slide, "Use these artifacts to convert technical feasibility into judge-ready proof", 64, 112, 900, 36, { fontSize: 21, color: "#B6C6D4" });
  const rows = [
    ["3D model and scale", "READY", "The archive includes model.glb and viewer_metadata.json. Add your viewer capture and demonstrate Shift-click measurement live."],
    ["Independent <1 m accuracy", "MISSING", "Collect holdout checkpoints, run validate-checkpoints, and show the 3D RMSE from the generated report."],
    ["Runtime improvement", "READY", "Use the editable runtime chart. State 28.81 minutes for the latest local evidence and 15 minutes as the remaining target."],
    ["Dynamic-object robustness", "MISSING", "Rerun with AI masking enabled and save one matched before-and-after frame plus its masked reconstruction result."],
    ["GIS interoperability", "VERIFIED", "Show dsm.tif in QGIS and point_cloud.las in CloudCompare. Both formats and EPSG:32610 metadata passed structural checks."],
  ];
  let y = 178;
  for (let i = 0; i < rows.length; i++) {
    const [label, state, action] = rows[i];
    const stateColor = state === "READY" || state === "VERIFIED" ? "#54D6A4" : state === "PARTIAL" ? "#F2B84B" : "#FF7C7C";
    addText(slide, String(i + 1).padStart(2, "0"), 66, y, 46, 30, { fontSize: 17, bold: true, color: C.cyan });
    addText(slide, label, 128, y, 310, 31, { fontSize: 21, bold: true, color: C.white });
    addText(slide, state, 455, y, 132, 31, { fontSize: 16, bold: true, color: stateColor });
    addText(slide, action, 610, y - 2, 584, 58, { fontSize: 17, color: "#D5E0E8" });
    addRect(slide, 64, y + 64, 1130, 1, "#284157");
    y += 92;
  }
  addText(slide, "Current conclusion", 64, 640, 190, 26, { fontSize: 16, bold: true, color: C.cyan });
  addText(slide, "End-to-end output generation is feasible. The speed and one-metre acceptance targets still require stronger evidence.", 268, 633, 926, 43, { fontSize: 20, bold: true, color: C.white });
  slide.speakerNotes.textFrame.setText([
    "End with a precise evidence plan instead of a broad claim.",
    "The supplied archive contains the GLB, LAS, GeoTIFF, point cloud, mesh, reports, and logs. It does not contain an independent checkpoint CSV.",
    "Production_ready is false in verification_report.json.",
  ]);
}

const requirements = {
  explicitTotalSlideCount: 7,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [4],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
};
const fontPolicy = { basis: "design", families: [font, mono] };
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "SIH26158_Feasibility_Evidence_Core_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

await finalizePresentation({
  ...requirements,
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
  requiredNativeTableOwnerSlides: [],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "SIH26158_Feasibility_Evidence_Core.validation.json"),
});

console.log(FINAL_PPTX);
