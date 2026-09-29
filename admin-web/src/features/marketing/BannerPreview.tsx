import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";

import { cn } from "@/lib/cn";

/** Plays a Lottie JSON with lottie-web's light build: it has no expression
 * engine, and the full build's `new Function` would be refused by the CSP. */
function Lottie({ url, className }: { url: string; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let destroyed = false;
    let anim: { destroy: () => void } | null = null;
    setFailed(false);
    void import("lottie-web/build/player/lottie_light")
      .then(({ default: lottie }) => {
        if (destroyed || !box.current) return;
        anim = lottie.loadAnimation({ container: box.current, renderer: "svg", loop: true, autoplay: true, path: url });
        (anim as unknown as { addEventListener: (e: string, cb: () => void) => void }).addEventListener("data_failed", () => setFailed(true));
      })
      .catch(() => setFailed(true));
    return () => {
      destroyed = true;
      anim?.destroy();
    };
  }, [url]);

  if (failed) {
    return (
      <span className={cn("flex flex-col items-center justify-center gap-1 text-xs text-gray-500", className)}>
        <Sparkles className="size-5" /> Lottie animation
      </span>
    );
  }
  return <div ref={box} className={className} />;
}

export function BannerPreview({ url, type, className }: { url: string; type: "IMAGE" | "GIF" | "LOTTIE"; className?: string }) {
  if (type === "LOTTIE") return <Lottie url={url} className={cn("bg-gray-50", className)} />;
  return <img src={url} alt="" className={cn("bg-gray-50 object-cover", className)} />;
}

export function inferMediaType(url: string | null): "IMAGE" | "GIF" | "LOTTIE" {
  if (!url) return "IMAGE";
  const path = url.split("?")[0].toLowerCase();
  if (path.endsWith(".gif")) return "GIF";
  if (path.endsWith(".json")) return "LOTTIE";
  return "IMAGE";
}
