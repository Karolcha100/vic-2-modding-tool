import { useState } from "react";
import type { OutlineNode } from "../api";

interface Props {
  items: OutlineNode[];
  cursor: number;
  onSelect: (node: OutlineNode) => void;
}

/** The syntax tree of the open file; clicking a node selects its text (K54 = D). */
export function Outline({ items, cursor, onSelect }: Props) {
  return (
    <div className="outline">
      {items.map((n, i) => (
        <OutlineItem key={i} node={n} depth={0} cursor={cursor} onSelect={onSelect} />
      ))}
    </div>
  );
}

function OutlineItem({ node, depth, cursor, onSelect }: { node: OutlineNode; depth: number } & Omit<Props, "items">) {
  const inside = node.start <= cursor && cursor <= node.end;
  // null: automatic (the top level and the branch with the cursor are open); a click decides
  // for good, also for the branch with the cursor (T016)
  const [open, setOpen] = useState<boolean | null>(null);
  const expanded = open ?? (depth < 1 || (inside && depth < 6));
  const label =
    node.kind === "assignment" ? node.key : node.kind === "block" ? "{ }" : node.kind === "error" ? `⚠ ${node.value}` : node.value;
  return (
    <div>
      <div
        className={"outline-row" + (inside ? " inside" : "") + (node.kind === "error" ? " error" : "")}
        style={{ paddingLeft: 6 + depth * 12 }}
        onClick={() => onSelect(node)}
      >
        {node.children ? (
          <span className="twisty" onClick={(e) => { e.stopPropagation(); setOpen(!expanded); }}>
            {expanded ? "▾" : "▸"}
          </span>
        ) : (
          <span className="twisty" />
        )}
        <span className="outline-key">{label}</span>
        {node.kind === "assignment" && node.value !== undefined && <span className="outline-value"> = {node.value}</span>}
        <span className="muted"> :{node.line}</span>
      </div>
      {expanded &&
        node.children?.map((c, i) => <OutlineItem key={i} node={c} depth={depth + 1} cursor={cursor} onSelect={onSelect} />)}
    </div>
  );
}
