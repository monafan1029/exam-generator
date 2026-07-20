import { useState } from "react";
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
  const [tab, setTab] = useState("documents");

  return (
    <div>
      <nav style={navStyles.bar}>
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
          <Component active={tab === key} />
        </div>
      ))}
    </div>
  );
}

const navStyles = {
  bar: {
    display: "flex",
    gap: 8,
    padding: "12px 24px",
    borderBottom: "1px solid #e5e7eb",
  },
  tab: {
    padding: "8px 20px",
    border: "none",
    background: "none",
    fontSize: 15,
    cursor: "pointer",
    borderRadius: 6,
  },
  tabActive: {
    background: "#2563eb",
    color: "#fff",
  },
};

export default App;