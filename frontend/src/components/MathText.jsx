/**
 * 混排文本渲染：把 $...$ 包裹的LaTeX公式渲染成数学式，其余按纯文本显示
 * 公式渲染失败时回退为原文，不阻塞页面
 */
import { InlineMath } from "react-katex";
import "katex/dist/katex.min.css";

export default function MathText({ children }) {
  const text = String(children ?? "");
  if (!text.includes("$")) return text;

  const parts = text.split(/(\$[^$]+\$)/g);
  return parts.map((part, i) => {
    if (part.length > 2 && part.startsWith("$") && part.endsWith("$")) {
      return (
        <InlineMath
          key={i}
          math={part.slice(1, -1)}
          renderError={() => <span>{part}</span>}
        />
      );
    }
    return <span key={i}>{part}</span>;
  });
}
