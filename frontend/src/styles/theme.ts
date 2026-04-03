import { alpha, createTheme, PaletteMode } from "@mui/material/styles";

export function buildTheme(mode: PaletteMode, fontScale: number) {
  const isDark = mode === "dark";

  return createTheme({
    palette: {
      mode,
      primary: {
        main: isDark ? "#76c4ff" : "#1267b5",
      },
      secondary: {
        main: isDark ? "#9ae6b4" : "#0f9f6e",
      },
      background: {
        default: isDark ? "#08111f" : "#eef3f8",
        paper: isDark ? "#0f1b2d" : "#ffffff",
      },
      text: {
        primary: isDark ? "#edf6ff" : "#14213d",
        secondary: isDark ? "#aac3de" : "#4b637d",
      },
      warning: {
        main: "#f59e0b",
      },
      error: {
        main: "#dc2626",
      },
      success: {
        main: "#059669",
      },
    },
    shape: {
      borderRadius: 18,
    },
    typography: {
      fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
      fontSize: Math.round(14 * fontScale),
      h1: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontWeight: 700,
      },
      h2: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontWeight: 700,
      },
      h3: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontWeight: 700,
      },
      h4: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontWeight: 700,
      },
      button: {
        textTransform: "none",
        fontWeight: 600,
      },
    },
    components: {
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            backdropFilter: "blur(18px)",
            backgroundColor: alpha(isDark ? "#0d1726" : "#fbfdff", 0.88),
            borderBottom: `1px solid ${alpha(isDark ? "#9fc2e4" : "#17395f", 0.12)}`,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
          },
          rounded: {
            borderRadius: 20,
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            border: `1px solid ${alpha(isDark ? "#e7f1ff" : "#17395f", 0.1)}`,
            boxShadow: isDark
              ? "0 20px 50px rgba(3, 12, 24, 0.35)"
              : "0 20px 50px rgba(15, 35, 64, 0.08)",
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 14,
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 14,
            backgroundColor: alpha(isDark ? "#132235" : "#ffffff", 0.72),
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            height: 4,
            borderRadius: 999,
          },
        },
      },
    },
  });
}