import type { BlockNode } from "../api";
import { pictureUrl } from "../api";

/** Event preview (K6 D): picture, title, description and options as the game shows them. */

const unquote = (v?: string) => (v ?? "").replace(/^"|"$/g, "");

/** Text of a title / desc / option name: its localisation, or the literal value. */
function text(node?: BlockNode): string {
  if (!node) return "";
  return node.loc_text ?? unquote(node.value);
}

function Paragraphs({ value }: { value: string }) {
  // Vic2 text: "\n" for new lines, "§Y…§W" colour codes, $VARIABLES$.
  const clean = value.replace(/§./g, "");
  return <>{clean.split("\\n").map((line, i) => <p key={i}>{line}</p>)}</>;
}

export function EventPreview({ event, onClose }: { event: BlockNode; onClose: () => void }) {
  const field = (key: string) => event.children?.find((c) => c.key?.toLowerCase() === key);
  const picture = unquote(field("picture")?.value);
  const options = event.children?.filter((c) => c.key?.toLowerCase() === "option") ?? [];
  return (
    <div className="preview-backdrop" onClick={onClose}>
      <div className="event-window" onClick={(e) => e.stopPropagation()}>
        <div className="event-title">{text(field("title")) || "(no title)"}</div>
        {picture && <img className="event-picture" src={pictureUrl(picture)} alt={picture} />}
        <div className="event-desc"><Paragraphs value={text(field("desc"))} /></div>
        {options.map((o, i) => {
          const name = o.children?.find((c) => c.key?.toLowerCase() === "name");
          return <div key={i} className="event-option">{text(name) || `(option ${i + 1})`}</div>;
        })}
        <div className="muted small">Preview - id {field("id")?.value ?? "?"}{field("is_triggered_only")?.value === "yes" ? " · triggered only" : ""}. Click outside to close.</div>
      </div>
    </div>
  );
}
