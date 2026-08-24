export const C = {
  ink: "#17201B",
  paper: "#F7F2E8",
  muted: "#7A8178",
  rule: "#C9C2B6",
  green: "#2F7D5A",
  blue: "#2D5BFF",
  amber: "#D88A22",
  red: "#B9473E",
  white: "#FFFFFF",
  paleGreen: "#DCEBDF",
  paleBlue: "#DDE6FF",
  paleAmber: "#F4E3C8",
};

export function bg(slide, color = C.paper) {
  slide.shapes.add({ geometry: "rect", position: { left: 0, top: 0, width: 1280, height: 720 }, fill: color });
}

export function text(slide, value, x, y, w, h, opts = {}) {
  const fill = opts.fill || opts.bg || C.paper;
  const props = { geometry: "rect", position: { left: x, top: y, width: w, height: h }, fill };
  if (opts.line) props.line = opts.line;
  const sh = slide.shapes.add(props);
  sh.text.set(value);
  sh.text.typeface = opts.typeface || "Arial";
  sh.text.fontSize = opts.size || 20;
  sh.text.color = opts.color || C.ink;
  sh.text.bold = Boolean(opts.bold);
  sh.text.alignment = opts.align || "left";
  sh.text.verticalAlignment = opts.valign || "mid";
  sh.text.insets = opts.insets || { top: 4, right: 6, bottom: 4, left: 6 };
  sh.text.wrap = "square";
  if (opts.autoFit) sh.text.autoFit = opts.autoFit;
  return sh;
}

export function title(slide, value, kicker, dark = false) {
  text(slide, kicker, 64, 38, 240, 26, {
    size: 13,
    bold: true,
    color: dark ? C.paleAmber : C.green,
    fill: dark ? C.ink : C.paper,
  });
  text(slide, value, 58, 76, 780, 92, {
    size: 40,
    bold: true,
    typeface: "Georgia",
    color: dark ? C.paper : C.ink,
    fill: dark ? C.ink : C.paper,
    valign: "top",
    autoFit: "shrinkText",
  });
}

export function footer(slide, source, n, dark = false) {
  text(slide, source, 58, 676, 860, 24, { size: 12, color: dark ? "#AAB4AA" : C.muted, fill: dark ? C.ink : C.paper });
  text(slide, String(n).padStart(2, "0"), 1190, 676, 42, 24, { size: 12, color: dark ? "#AAB4AA" : C.muted, fill: dark ? C.ink : C.paper, align: "right" });
}

export function rule(slide, x, y, w, color = C.rule) {
  slide.shapes.add({ geometry: "rect", position: { left: x, top: y, width: w, height: 1.2 }, fill: color });
}

export function panel(slide, x, y, w, h, fill = C.white) {
  return slide.shapes.add({ geometry: "rect", position: { left: x, top: y, width: w, height: h }, fill });
}

export function metric(slide, value, label, x, y, w, color = C.green, fill = C.paper) {
  text(slide, value, x, y, w, 44, { size: 32, bold: true, color, fill, typeface: "Georgia" });
  text(slide, label, x, y + 46, w, 34, { size: 14, color: C.muted, fill, valign: "top" });
}

export function hbar(slide, label, valueText, pct, x, y, w, color) {
  text(slide, label, x, y - 2, 230, 28, { size: 16, bold: true });
  slide.shapes.add({ geometry: "rect", position: { left: x + 250, top: y + 5, width: w, height: 16 }, fill: "#E6DFD4" });
  slide.shapes.add({ geometry: "rect", position: { left: x + 250, top: y + 5, width: Math.max(1, w * pct), height: 16 }, fill: color });
  text(slide, valueText, x + 250 + w + 18, y - 1, 120, 28, { size: 16, color: C.ink, bold: true });
}

export function node(slide, label, sub, x, y, w, h, fill, color = C.ink) {
  panel(slide, x, y, w, h, fill);
  text(slide, label, x + 14, y + 12, w - 28, 26, { size: 18, bold: true, color, fill });
  text(slide, sub, x + 14, y + 42, w - 28, h - 52, { size: 13, color: C.muted, fill, valign: "top", autoFit: "shrinkText" });
}

export function connector(slide, x1, y, x2, color = C.muted) {
  slide.shapes.add({ geometry: "rect", position: { left: x1, top: y, width: x2 - x1, height: 2 }, fill: color });
  slide.shapes.add({ geometry: "triangle", position: { left: x2 - 4, top: y - 5, width: 12, height: 12 }, fill: color });
}
