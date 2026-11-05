export function text(node) {
  if (node === null || node === undefined || node === false) { return ""; }
  if (typeof node === "string" || typeof node === "number") { return String(node); }
  if (Array.isArray(node)) { return node.map(text).join(" "); }
  if (typeof node.type === "function") { return text(node.type(node.props || {})); }
  const kids = node.props && node.props.children;
  return text(kids);
}

export function every(node, out = []) {
  if (!node || typeof node !== "object") { return out; }
  if (Array.isArray(node)) { node.forEach((one) => every(one, out)); return out; }
  if (typeof node.type === "function") { return every(node.type(node.props || {}), out); }
  out.push(node);
  return every(node.props && node.props.children, out);
}

export function find(node, className, out = []) {
  if (!node || typeof node !== "object") { return out; }
  if (Array.isArray(node)) { node.forEach((one) => find(one, className, out)); return out; }
  if (typeof node.type === "function") { return find(node.type(node.props || {}), className, out); }
  const cls = (node.props && node.props.class) || "";
  if (String(cls).split(" ").includes(className)) { out.push(node); }
  return find(node.props && node.props.children, className, out);
}
