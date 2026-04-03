import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Box, CircularProgress, CssBaseline, useMediaQuery } from "@mui/material";
import { ThemeProvider } from "@mui/material/styles";

import { buildTheme } from "../styles/theme";
import { useSession } from "../state/SessionProvider";

const LandingPage = lazy(() => import("../pages/LandingPage"));
const WorkspacePage = lazy(() => import("../pages/WorkspacePage"));

function RouteLoader() {
  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <CircularProgress size={42} />
    </Box>
  );
}

function AppRoutes() {
  const { session } = useSession();

  return (
    <Suspense fallback={<RouteLoader />}>
      <Routes>
        <Route
          path="/"
          element={session?.authenticated ? <Navigate to="/workspace" replace /> : <LandingPage />}
        />
        <Route
          path="/workspace"
          element={session?.authenticated ? <WorkspacePage /> : <Navigate to="/" replace />}
        />
        <Route path="*" element={<Navigate to={session?.authenticated ? "/workspace" : "/"} replace />} />
      </Routes>
    </Suspense>
  );
}

export default function App() {
  const { session, loading } = useSession();
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const requestedMode = session?.preferences.theme_mode ?? "system";
  const mode = requestedMode === "system" ? (prefersDark ? "dark" : "light") : requestedMode;
  const fontScale = session?.preferences.font_scale ?? 1;
  const theme = buildTheme(mode, fontScale);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {loading ? (
        <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
          <CircularProgress size={42} />
        </Box>
      ) : (
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      )}
    </ThemeProvider>
  );
}