import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'Knowledge Hub | Local foundation', description: 'A local foundation for traceable document knowledge.' };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
