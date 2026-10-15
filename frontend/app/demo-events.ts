import type { EventLifetime } from '@borwood/demoable-react';
// No filenames, questions, answer values, IDs, payloads or credentials enter the log.
export const eventLifetime: EventLifetime = { type: 'completion', succeeded: 30000, failed: 60000, cancelled: 10000 };
