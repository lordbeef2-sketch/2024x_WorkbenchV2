import { alpha, createTheme, PaletteMode } from "@mui/material/styles";

export function buildTheme(mode: PaletteMode, fontScale: number, compactUi = true) {
  const isDark = mode === "dark";
  const baseFontSize = compactUi ? 13 : 14;
  const controlRadius = compactUi ? 10 : 14;
  const surfaceRadius = compactUi ? 12 : 20;
  const tabMinHeight = compactUi ? 40 : 48;
  const toolbarMinHeight = compactUi ? 46 : 56;

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
      borderRadius: compactUi ? 12 : 18,
    },
    typography: {
      fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
      fontSize: Math.round(baseFontSize * fontScale),
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
      MuiToolbar: {
        styleOverrides: {
          root: {
            minHeight: toolbarMinHeight,
            "@media (min-width:600px)": {
              minHeight: toolbarMinHeight,
            },
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
          },
          rounded: {
            borderRadius: surfaceRadius,
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
        defaultProps: {
          size: compactUi ? "small" : "medium",
        },
        styleOverrides: {
          root: {
            borderRadius: controlRadius,
          },
        },
      },
      MuiIconButton: {
        defaultProps: {
          size: compactUi ? "small" : "medium",
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            height: compactUi ? 24 : 32,
            fontSize: compactUi ? "0.75rem" : "0.8125rem",
          },
        },
      },
      MuiTextField: {
        defaultProps: {
          size: compactUi ? "small" : "medium",
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: controlRadius,
            backgroundColor: alpha(isDark ? "#132235" : "#ffffff", 0.72),
          },
        },
      },
      MuiAccordionSummary: {
        styleOverrides: {
          root: {
            minHeight: compactUi ? 40 : 48,
            "&.Mui-expanded": {
              minHeight: compactUi ? 40 : 48,
            },
          },
          content: {
            margin: compactUi ? "8px 0" : "12px 0",
            "&.Mui-expanded": {
              margin: compactUi ? "8px 0" : "12px 0",
            },
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
      MuiTab: {
        styleOverrides: {
          root: {
            minHeight: tabMinHeight,
            padding: compactUi ? "6px 12px" : "10px 16px",
            fontSize: compactUi ? "0.8125rem" : "0.875rem",
          },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            paddingTop: compactUi ? 4 : 8,
            paddingBottom: compactUi ? 4 : 8,
          },
        },
      },
    },
  });
}
