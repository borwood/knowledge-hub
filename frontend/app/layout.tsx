import type { Metadata } from 'next';
import '@borwood/demoable-react/styles.css';
import './globals.css';
import DemoShell from './demo-shell';
export const metadata: Metadata = { title: 'Knowledge Hub | Local foundation', description: 'A local foundation for traceable document knowledge.' };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><DemoShell>{children}</DemoShell></body></html>;
}
