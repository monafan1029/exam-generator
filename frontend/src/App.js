import { useState } from "react";
import HomePage from "./pages/HomePage";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewPage from "./pages/ReviewPage";
import ExamPage from "./pages/ExamPage";
import HistoryPage from "./pages/HistoryPage";


const TABS = [
  { key: "documents", label: "教材管理", Component: DocumentsPage },
  { key: "exam", label: "组卷", Component: ExamPage },
  { key: "review", label: "题库管理", Component: ReviewPage },
  { key: "history", label: "历史试卷", Component: HistoryPage },
];

function App() {
  const [view, setView] = useState("home"); // "home" | "app"
  const [tab, setTab] = useState("documents");
  // 历史页"继续出题/继续审核"时传给组卷页的目标试卷 {paperId, taskId?}
  const [openPaper, setOpenPaper] = useState(null);

  const handleOpenPaper = (paperId, taskId) => {
    setOpenPaper({ paperId, taskId });
    setTab("exam");
  };

  if (view === "home") {
    return <HomePage onEnter={() => setView("app")} />;
  }

  return (
    <div>
      <nav style={navStyles.bar}>
        <span style={navStyles.brand} onClick={() => setView("home")}>
          <span style={navStyles.brandMark}>智</span>
          智能出题系统
        </span>
        {TABS.map((t) => (
          <button
            key={t.key}
            style={{
              ...navStyles.tab,
              ...(tab === t.key ? navStyles.tabActive : {}),
            }}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {TABS.map(({ key, Component }) => (
        <div key={key} style={{ display: tab === key ? "block" : "none" }}>
          <Component
            active={tab === key}
            {...(key === "exam"
              ? { openPaper, onOpenHandled: () => setOpenPaper(null) }
              : {})}
            {...(key === "history" ? { onOpenPaper: handleOpenPaper } : {})}
          />
        </div>
      ))}
    </div>
  );
}

const navStyles = {
  bar: {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "0 28px",
    height: 58,
    background: "#ffffff",
    borderBottom: "1px solid #ecedf0",
    boxShadow: "0 1px 3px rgba(15, 23, 42, 0.04)",
    position: "sticky",
    top: 0,
    zIndex: 100,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontWeight: 700,
    fontSize: 16,
    letterSpacing: "-0.01em",
    color: "#0f172a",
    marginRight: 28,
    cursor: "pointer",
  },
  brandMark: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 28,
    height: 28,
    borderRadius: 8,
    background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
    color: "#fff",
    fontSize: 15,
    fontWeight: 700,
  },
  tab: {
    padding: "8px 16px",
    border: "none",
    background: "none",
    fontSize: 14.5,
    fontWeight: 500,
    color: "#52525b",
    cursor: "pointer",
    borderRadius: 8,
  },
  tabActive: {
    background: "#eef4ff",
    color: "#2563eb",
    fontWeight: 600,
  },
};

export default App;