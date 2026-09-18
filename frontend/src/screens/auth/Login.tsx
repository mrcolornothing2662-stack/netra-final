import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { login, isAuthenticated, clearToken, getStoredUser, ApiError } from "../../api/client";
import { Icon } from "../../components/icons";
import { prefersReducedMotion } from "./scene/quality";
import s from "./login.module.css";

// The 3D world is code-split: the auth form paints immediately, the scene
// streams in behind it. If WebGL is unavailable the CSS backdrop stands in.
const LoginScene = lazy(() => import("./scene/LoginScene"));

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    /* WebGL unavailable — the CSS backdrop already covers the page */
  }
  render() {
    if (this.state.failed) return <div className={s.backdrop} aria-hidden />;
    return this.props.children;
  }
}

/**
 * Explicit sign-in over the living intelligence world. There is no auto-login
 * and no hardcoded credential: the investigator authenticates against the
 * backend, and only a valid token grants access. On failure we surface the
 * backend's real reason — nothing is fabricated.
 */
export function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  // Only permit same-origin, absolute in-app paths as the post-login target.
  const rawNext = params.get("next");
  const next = rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/command";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reducedMotion] = useState(() => prefersReducedMotion());
  const [currentUser, setCurrentUser] = useState(() => (isAuthenticated() ? getStoredUser() : null));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      const user = await login(username.trim(), password);
      if (user.must_change_password) {
        navigate("/change-password", { replace: true });
      } else {
        navigate(next, { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <div className={s.page}>
      <div className={s.world} aria-hidden>
        <SceneBoundary>
          <Suspense fallback={<div className={s.backdrop} />}>
            <LoginScene reduced={reducedMotion} />
          </Suspense>
        </SceneBoundary>
      </div>
      <div className={s.vignette} aria-hidden />

      <Link to="/" className={s.back}>
        ← Overview
      </Link>

      <motion.section
        className={s.panel}
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        aria-label="CyberDrishti control access"
      >
        <div className={s.hudHeader}>
          <div className={s.statusPill}>
            <span className={s.statusDot} />
            <span>3D SPATIAL THREAT MESH // ONLINE</span>
          </div>
          <span className={s.hudCode}>SEC-AUTH // 256-BIT</span>
        </div>

        <motion.header
          className={s.brand}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className={s.brandIcon}><Icon name="logo" size={18} /></span>
          <div>
            <h1 className={s.title}>CYBERDRISHTI</h1>
            <p className={s.subtitle}>CONTROL ACCESS</p>
          </div>
        </motion.header>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25, duration: 0.5 }}
        >
          <div className={s.rule} />
          <p className={s.kicker}>ADMIN ACCESS</p>
        </motion.div>

        {error && (
          <motion.div
            className={s.error}
            role="alert"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
          >
            {error}
          </motion.div>
        )}

        {isAuthenticated() && currentUser ? (
          <div className={s.sessionActive}>
            <p className={s.activeBadge}>● OFFICER SESSION ACTIVE</p>
            <div className={s.userInfo}>
              <strong>{currentUser.full_name || currentUser.username}</strong>
              <span>Role: {currentUser.role.toUpperCase()}{currentUser.unit ? ` · ${currentUser.unit}` : ""}</span>
            </div>
            <button
              className={s.submit}
              type="button"
              onClick={() => {
                if (currentUser.must_change_password) {
                  navigate("/change-password", { replace: true });
                } else {
                  navigate(next, { replace: true });
                }
              }}
            >
              ENTER COMMAND CENTER <Icon name="arrow" size={15} />
            </button>
            <button
              className={s.switchBtn}
              type="button"
              onClick={() => {
                clearToken();
                setCurrentUser(null);
              }}
            >
              Sign In as Different Officer
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} noValidate>
            <motion.div
              className={s.field}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            >
              <label className={s.label} htmlFor="login-username">Officer ID</label>
              <input
                id="login-username"
                className={s.input}
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
              />
            </motion.div>

            <motion.div
              className={s.field}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.38, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            >
              <label className={s.label} htmlFor="login-password">Secure Password</label>
              <input
                id="login-password"
                type="password"
                className={s.input}
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </motion.div>

            <motion.button
              className={s.submit}
              type="submit"
              disabled={submitting || !username.trim() || !password}
              aria-busy={submitting}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.46, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.985 }}
            >
              {submitting ? "AUTHENTICATING" : "AUTHENTICATE"}
              {!submitting && <Icon name="arrow" size={15} />}
            </motion.button>
          </form>
        )}

        <motion.div
          className={s.secureRule}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.55, duration: 0.6 }}
        >
          <span>SECURE ACCESS</span>
        </motion.div>

        <motion.p
          className={s.audit}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.6 }}
        >
          Authorized personnel only. All access is recorded to the SHA-256 audit chain.
        </motion.p>
      </motion.section>

      <motion.p
        className={s.caption}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.9, duration: 0.8 }}
        aria-hidden
      >
        CYBER INTELLIGENCE PLATFORM · LIVE CORRELATION GRID
      </motion.p>
    </div>
  );
}
