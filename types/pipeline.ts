export interface DQGateResult {
  passed: boolean;
  score: number;
  threshold: number;
  force_unlocked: boolean;
  has_high_pii: boolean;
  details: {
    null_score: number;
    type_score: number;
    duplicate_score: number;
    outlier_score: number;
  };
  datasets?: Record<string, {
    dq_score: number;
    grade: 'A' | 'B' | 'C' | 'F';
    phase2_allowed: boolean;
    reason: string;
  }>;
}

export interface ManualReviewItem {
  id: string;
  dataset?: string;
  column?: string;
  issue_type: string;
  severity: string;
  message: string;
  guidance?: string;
  default_resolution?: string;
}

export interface ValidationResult {
  success: boolean;
  checks: Array<{
    id: string;
    label: string;
    status: 'success' | 'warning' | 'error';
    message?: string;
  }>;
}

export interface SemanticDescriptor {
  semantic_type: string;
  sub_type: string;
  pii_level: 'none' | 'low' | 'medium' | 'high';
  confidence: number;
  inferred_by: 'heuristic' | 'llm' | 'user_override';
  allowed_domain?: string[] | null;
  valid_range?: { min: number; max: number } | null;
  expected_format?: string | null;
  fill_strategy: string;
  transform_hints: string[];
  original_semantic_type?: string | null;
}
