export interface Message {
  id: string;
  text: string;
  sender: 'user' | 'bot';
  timestamp: Date;
  /** Optional structured payload from backend, used for rich rendering (tables, metadata, etc.). */
  payload?: any;
  options?: Array<{
    id: string;
    text: string;
    /** The exact user text to send when clicked. */
    send: string;
  }>;
}

export interface TransformationStep {
  id: string;
  type: string;
  parameters: Record<string, any>;
  order: number;
}

export interface DataSource {
  type: 'File' | 'Database' | 'Azure Blob' | 'API';
}

export interface TransformationType {
  value: string;
  label: string;
}

export const TRANSFORMATION_TYPES: TransformationType[] = [
  { value: 'rename', label: 'Rename Columns' },
  { value: 'datatype', label: 'Change Data Types' },
  { value: 'filter', label: 'Filter Rows' },
  { value: 'drop', label: 'Drop Columns' },
  { value: 'aggregate', label: 'Aggregate' },
  { value: 'join', label: 'Join/Merge' },
  { value: 'normalize', label: 'Normalize' },
  { value: 'custom', label: 'Custom Script' },
];

export const QUICK_PROMPTS = [
  'Clean null values',
  'Standardize date formats',
  'Join sales and customer tables',
  'Detect anomalies',
  'Aggregate monthly revenue',
];
