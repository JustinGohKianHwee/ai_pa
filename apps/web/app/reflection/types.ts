export interface CcyAmount {
  currency: string;
  amount: number;
}

export interface GoalProgress {
  id: string;
  title: string | null;
  target: string | null;
  target_date: string | null;
}

export interface WeeklyReflection {
  kind: "weekly";
  week_start: string;
  week_end: string;
  confirmed_by_domain: Record<string, number>;
  spend_week: CcyAmount[];
  spend_prev_week: CcyAmount[];
  portfolio_delta_week: CcyAmount[];
  wins: string[];
  concerns: string[];
  trends: string[];
  progress: GoalProgress[];
}

export interface ReflectionResponse {
  timezone: string;
  reflection: WeeklyReflection;
}
