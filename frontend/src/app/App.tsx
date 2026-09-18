import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { RequireAuth } from "./RequireAuth";
import { ScrollToTop } from "./ScrollToTop";
import { EnterOverlay } from "./EnterOverlay";
import { Landing } from "../screens/landing/Landing";
import { Login } from "../screens/auth/Login";
import { ChangePassword } from "../screens/auth/ChangePassword";
import { CommandCenter } from "../screens/command/CommandCenter";
import { Investigations } from "../screens/investigations/Investigations";
import { CaseScreen } from "../screens/case/CaseScreen";
import { Intelligence } from "../screens/intelligence/Intelligence";
import { Settings } from "../screens/settings/Settings";

export function App() {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <EnterOverlay />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<ChangePassword />} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route path="/command" element={<CommandCenter />} />
          <Route path="/investigations" element={<Investigations />} />
          <Route path="/investigations/:caseId" element={<CaseScreen />} />
          <Route path="/investigations/:caseId/:tab" element={<CaseScreen />} />
          <Route path="/case/:caseId" element={<CaseScreen />} />
          <Route path="/case/:caseId/:tab" element={<CaseScreen />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
