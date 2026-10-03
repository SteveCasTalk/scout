import type { Metadata } from 'next';
import { Documentation } from '@/components/documentation';
import { brand } from '@/lib/brand';

export const metadata: Metadata = {
  title: `Documentation · ${brand.name}`,
  description: `${brand.name} concepts, testing philosophy, setup, MCP integrations, verification, sandbox scenarios, and review workflows.`,
};

// Static product documentation contains no workspace or account data.
export default function DocumentationPage() {
  return <Documentation/>;
}
