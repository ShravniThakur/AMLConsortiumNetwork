"use client";

import { usePathname } from "next/navigation";

const AUTH_ROUTES = ["/login"];

export default function ContentWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuth = AUTH_ROUTES.includes(pathname);

  if (isAuth) {
    // Auth pages: full screen, no sidebar offset
    return <div className="min-h-screen flex flex-col">{children}</div>;
  }

  // Dashboard pages: offset for 264px sidebar
  return (
    <div style={{ marginLeft: "264px" }} className="min-h-screen flex flex-col">
      {children}
    </div>
  );
}
