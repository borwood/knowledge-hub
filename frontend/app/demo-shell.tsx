'use client';
import { DemoLayout, InspectionProvider, useInspection } from '@borwood/demoable-react';
import { useEffect, useState } from 'react';

export function DemoToggle() {
  const { active, setActive } = useInspection();
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const query = matchMedia('(hover: none) and (pointer: coarse)');
    const update = () => setMobile(query.matches);
    update(); query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return mobile ? <span className="muted">Demo inspection active · use settings to choose layers</span> :
    <button aria-pressed={active} onClick={() => setActive(!active)}>{active ? 'Disable' : 'Enable'} demo inspection</button>;
}

export default function DemoShell({ children }: { children: React.ReactNode }) {
  return <InspectionProvider><DemoLayout className="hub-demo" appClassName="hub-demo-app" orientation={<p><strong>Upload → question → evidence.</strong> Inspect the ? markers for engineering context. Events explain actual work. Desktop: press ? to show or hide.</p>}>
    {children}
  </DemoLayout></InspectionProvider>;
}
