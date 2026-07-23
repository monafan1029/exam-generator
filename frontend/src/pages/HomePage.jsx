/**
 * 首页 / 落地页
 * hero区：左侧文案+CTA，右侧AI生成的插画（已裁掉插画自带的标题文字，
 * 标题改用真实HTML渲染，可缩放、可被读屏器读取）
 */
import heroIllustration from "../assets/hero-illustration-cropped.jpg";

export default function HomePage({ onEnter }) {
  return (
    <div style={s.page}>
      <div style={s.hero}>
        <div style={s.left}>
          <h1 style={s.title}>智能出题系统</h1>
          <p style={s.subtitle}>让出题更轻松，测评更科学</p>
          <p style={s.desc}>
            基于AI技术，一键生成高质量、个性化测试试题库。
          </p>
          <button style={s.cta} onClick={onEnter}>
            进入系统
          </button>
        </div>
        <div style={s.right}>
          <img
            src={heroIllustration}
            alt="AI智能出题系统界面示意：教师在大屏前演示出题流程，学生在笔记本电脑上作答"
            style={s.image}
          />
        </div>
      </div>
    </div>
  );
}

const s = {
  page: {
    minHeight: "100vh",
    background: "linear-gradient(135deg, #eaf2fd 0%, #f7fafd 55%, #ffffff 100%)",
  },
  hero: {
    maxWidth: 1180,
    margin: "0 auto",
    padding: "0 32px",
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    gap: 48,
    flexWrap: "wrap",
  },
  left: {
    flex: "1 1 380px",
    minWidth: 320,
    paddingTop: 40,
    paddingBottom: 40,
  },
  title: {
    fontSize: "clamp(34px, 5vw, 52px)",
    fontWeight: 800,
    color: "#0b0b0b",
    margin: 0,
    lineHeight: 1.15,
    letterSpacing: "-0.02em",
  },
  subtitle: {
    fontSize: "clamp(18px, 2.4vw, 23px)",
    fontWeight: 600,
    color: "#2563eb",
    margin: "18px 0 0",
  },
  desc: {
    fontSize: 16,
    color: "#52514e",
    lineHeight: 1.8,
    margin: "16px 0 0",
    maxWidth: 440,
  },
  cta: {
    marginTop: 32,
    padding: "13px 34px",
    fontSize: 16,
    fontWeight: 600,
    color: "#fff",
    background: "#2563eb",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    boxShadow: "0 8px 20px rgba(37,99,235,0.28)",
  },
  right: {
    flex: "1 1 420px",
    minWidth: 300,
    display: "flex",
    justifyContent: "center",
  },
  image: {
    width: "100%",
    maxWidth: 560,
    height: "auto",
    borderRadius: 16,
    boxShadow: "0 24px 60px rgba(11,11,11,0.16)",
  },
};
