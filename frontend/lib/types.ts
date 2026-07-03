// TS mirrors of Pydantic response shapes in backend/app/models.py

export interface HealthResponse {
  status: string;
  app_env: string;
}
