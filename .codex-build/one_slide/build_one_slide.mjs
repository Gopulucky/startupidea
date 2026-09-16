import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "D:\\sih_drone_pipeline";
const SKILL_DIR = "C:\\Users\\gopuh\\.codex\\plugins\\cache\\openai-primary-runtime\\presentations\\26.905.11957\\skills\\presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-build", "one_slide");
const FINAL_PPTX = path.join(workspaceDir, "deliverables", "SIH26158_Feasibility_One_Slide_Final.pptx");
const RUNTIME_PYTHON = "C:\\Users\\gopuh\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";

const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });

const font = resolvePresentationFont({ fontFamily: "Arial" });
const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const slide = presentation.slides.add();

const C = {
  background: "#FBFCFE",
  navy: "#173C63",
  ink: "#172331",
  body: "#293A4B",
  teal: "#0E9F9A",
  coral: "#C86C6C",
  line: "#D6DEE6",
  paleBlue: "#F1F7FB",
  paleTeal: "#F1FAF8",
  paleWarm: "#FFF9F5",
};

slide.background.fill = C.background;

function addRect(left, top, width, height, fill) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: "none", width: 0 },
  });
}

function addText(text, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: font,
    fontSize: options.fontSize ?? 22,
    bold: options.bold ?? false,
    color: options.color ?? C.body,
    autoFit: options.autoFit ?? "shrinkText",
    alignment: options.alignment ?? "left",
    verticalAlignment: "top",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addHeading(text, left, top, width) {
  addText(text, left, top, width, 38, { fontSize: 29, bold: true, color: C.navy, autoFit: "none" });
  addRect(left, top + 41, 74, 4, C.teal);
}

function addBullets(items, left, top, width, height) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = items.map(([lead, body]) => ({
    bulletCharacter: "•",
    marginLeft: 18 * 12700,
    indent: -10 * 12700,
    spaceAfter: 620,
    runs: [
      { run: `${lead}: `, textStyle: { bold: true, typeface: font, fontSize: "16.5pt", color: C.ink } },
      { run: body, textStyle: { typeface: font, fontSize: "16.5pt", color: C.body } },
    ],
  }));
  shape.text.style = {
    typeface: font,
    fontSize: 22,
    color: C.body,
    autoFit: "shrinkText",
    verticalAlignment: "top",
    insets: { top: 0, right: 4, bottom: 0, left: 0 },
  };
  return shape;
}

// Subtle quadrant backgrounds inspired by the supplied reference.
addRect(0, 0, 640, 360, C.paleBlue);
addRect(640, 360, 640, 360, C.paleTeal);
addRect(0, 360, 640, 360, C.paleWarm);

// Central separators.
addRect(638, 18, 2, 684, C.coral);
addRect(18, 358, 1244, 2, C.coral);

const left = 34;
const right = 674;

addHeading("Technical feasibility", left, 23, 540);
addBullets([
  ["End-to-end pipeline", "One 4.19-minute flight produced a georeferenced reconstruction from 253 selected frames."],
  ["Verified output", "604,982 coloured points, a 361,510-face mesh, and a textured GLB were generated."],
  ["GIS interoperability", "LAS and GeoTIFF passed structural checks with EPSG:32610 metadata."],
  ["Reconstruction quality", "Mean reprojection error reached 0.458 px and the capture-quality screen passed."],
], left, 79, 570, 260);

addHeading("Implementation feasibility", right, 23, 550);
addBullets([
  ["GPU workflow", "COLMAP 4.2 used CUDA on a Tesla T4. Dense stereo reached 100% peak GPU use."],
  ["Runtime progress", "Wall time fell from 80.75 to 28.81 minutes, a 64% reduction across documented runs."],
  ["Automated operation", "One Colab command handles keyframes, telemetry, reconstruction, export and verification."],
  ["Metric viewer", "GLB and metadata preserve local ENU coordinates for distance measurement."],
], right, 79, 570, 260);

addHeading("Current challenges", left, 382, 540);
addBullets([
  ["Runtime target", "The latest 28.81-minute run remains above the required 15 minutes."],
  ["Accuracy evidence", "Independent checkpoint RMSE is absent. The 1.835 m GPS RMSE is only a camera diagnostic."],
  ["Registration", "81.82% of selected images registered, below the current 90% production gate."],
  ["Coverage and robustness", "DSM coverage is 13.84%, and the archived run skipped dynamic-object masking."],
], left, 438, 570, 248);

addHeading("Evidence and improvement strategy", right, 382, 570);
addBullets([
  ["Accuracy proof", "Survey at least three holdout checkpoints and report 3D RMSE below 1.0 m."],
  ["Runtime focus", "Optimize dense stereo and sparse mapping. The measured run needs a further 1.92x speedup."],
  ["Capture improvement", "Increase overlap and use camera calibration to improve registration and DSM coverage."],
  ["Judge demonstration", "Add the viewer measurement, QGIS DSM, CloudCompare LAS, and an AI-mask comparison."],
], right, 438, 570, 248);

addText("Evidence source: optimized_v1 output archive, run_report.json and verification_report.json", 34, 697, 880, 16, {
  fontSize: 11, color: "#68798A", autoFit: "none",
});

slide.speakerNotes.textFrame.setText([
  "Sources: optimized_v1/run_report.json; optimized_v1/verification_report.json; optimized_v1/preflight.json; optimized_v1/capture_quality.json.",
  "The archive confirms valid GLB, LAS and GeoTIFF products, 604,982 points, 361,510 mesh faces, 28.81-minute wall time, 81.82% registration and 0.457586 px mean reprojection error.",
  "Accuracy boundary: surveyed checkpoints and dense reference geometry are absent, so the one-metre surface target remains unevaluated.",
  "The team will provide the viewer demonstration separately.",
]);

const stagingDir = path.join(workspaceDir, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "SIH26158_Feasibility_One_Slide_Final_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

await finalizePresentation({
  explicitTotalSlideCount: 1,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
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
  receiptPath: path.join(stagingDir, "SIH26158_Feasibility_One_Slide_Final.validation.json"),
});

console.log(FINAL_PPTX);
