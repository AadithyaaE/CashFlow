import { r as reactExports, j as jsxRuntimeExports } from "../_libs/react.mjs";
function ScreenFrame({ src, title }) {
  reactExports.useEffect(() => {
    window.VITE_OCR_API_KEY = "K82301801788957";
  }, []);
  return /* @__PURE__ */ jsxRuntimeExports.jsx(
    "iframe",
    {
      src,
      title,
      style: { width: "100vw", height: "100vh", border: 0, display: "block" }
    }
  );
}
export {
  ScreenFrame as S
};
