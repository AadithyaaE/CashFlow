export default function ScreenFrame({ src, title }: { src: string; title: string }) {
  return (
    <iframe
      src={src}
      title={title}
      style={{ width: "100vw", height: "100vh", border: 0, display: "block" }}
    />
  );
}
