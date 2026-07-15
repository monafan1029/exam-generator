import { useState } from "react";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewPage from "./pages/ReviewPage";
import ExamPage from "./pages/ExamPage";


const TABS = [
  { key: "documents", label: "教材管理", component: <DocumentsPage /> },
  { key: "exam", label: "组卷", component: <ExamPage /> },
  { key: "review", label: "题库管理", component: <ReviewPage /> },
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
      {TABS.find((t) => t.key === tab)?.component}
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