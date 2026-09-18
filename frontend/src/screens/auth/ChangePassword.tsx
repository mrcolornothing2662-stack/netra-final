import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { changePassword, getStoredUser, ApiError, logout } from "../../api/client";
import { Icon } from "../../components/icons";
import s from "./login.module.css";

export function ChangePassword() {
  const navigate = useNavigate();
  const user = getStoredUser();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword || !newPassword) return;

    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    if (newPassword === currentPassword) {
      setError("New password must differ from current password.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await changePassword(currentPassword, newPassword);
      navigate("/command", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Password update failed. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <div className={s.page}>
      <div className={s.backdrop} aria-hidden />
      <div className={s.vignette} aria-hidden />

      <motion.section
        className={s.panel}
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        aria-label="Mandatory Password Update"
      >
        <div className={s.hudHeader}>
          <div className={s.statusPill}>
            <span className={s.statusDot} style={{ background: "#f59e0b" }} />
            <span>SECURITY NOTICE // MANDATORY UPDATE</span>
          </div>
          <span className={s.hudCode}>SEC-ENFORCE // FIRST-LOGIN</span>
        </div>

        <motion.header
          className={s.brand}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className={s.brandIcon}><Icon name="logo" size={18} /></span>
          <div>
            <h1 className={s.title}>PASSWORD UPDATE</h1>
            <p className={s.subtitle}>
              {user ? `OFFICER: ${user.username.toUpperCase()}` : "AUTHENTICATED SESSION"}
            </p>
          </div>
        </motion.header>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.25, duration: 0.5 }}
        >
          <div className={s.rule} />
          <p className={s.kicker} style={{ color: "#fbbf24" }}>
            POLICY REQUIREMENT: INITIAL / DEFAULT CREDENTIAL MUST BE ROTATED
          </p>
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

        <form onSubmit={handleSubmit} noValidate>
          <motion.div
            className={s.field}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          >
            <label className={s.label} htmlFor="current-password">Current Password</label>
            <input
              id="current-password"
              type="password"
              className={s.input}
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
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
            <label className={s.label} htmlFor="new-password">New Password (min 8 chars)</label>
            <input
              id="new-password"
              type="password"
              className={s.input}
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </motion.div>

          <motion.div
            className={s.field}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.44, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          >
            <label className={s.label} htmlFor="confirm-password">Confirm New Password</label>
            <input
              id="confirm-password"
              type="password"
              className={s.input}
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          >
            <button
              className={s.submit}
              type="submit"
              disabled={submitting || !currentPassword || !newPassword || !confirmPassword}
            >
              {submitting ? "UPDATING PASSWORD..." : "CONFIRM & PROCEED"}
              <Icon name="arrow" size={15} />
            </button>
          </motion.div>
        </form>

        <div style={{ marginTop: "16px", textAlign: "center" }}>
          <button
            type="button"
            className={s.switchBtn}
            onClick={() => logout()}
          >
            Sign Out
          </button>
        </div>
      </motion.section>
    </div>
  );
}
