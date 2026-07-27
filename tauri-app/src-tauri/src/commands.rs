use serde::{Deserialize, Serialize};

const API_BASE: &str = "http://localhost:8000/api/v1";

// ============================================================================
// Data Structures (matching FastAPI responses)
// ============================================================================

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DashboardData {
    pub project_count: u32,
    pub feature_count: u32,
    pub document_count: u32,
    pub today_feature: Option<FeatureInfo>,
    pub recent_features: Vec<FeatureInfo>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FeatureInfo {
    pub id: String,
    pub title: String,
    pub pareto_score: f64,
    pub status: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FeatureBacklogItem {
    pub id: String,
    pub title: String,
    pub description: String,
    pub pareto_score: f64,
    pub impact_score: u32,
    pub effort_score: u32,
    pub risk_score: u32,
    pub category: String,
    pub status: String,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GraphData {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub mermaid_syntax: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GraphNode {
    pub id: String,
    pub r#type: String,
    pub title: String,
    pub status: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    pub r#type: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WizardStartResult {
    pub success: bool,
    pub session_id: String,
    pub feature_node_id: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WizardStepResult {
    pub success: bool,
    pub step: u32,
    pub content: String,
    pub verification_score: f64,
    pub passed: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct YoloGenerationResult {
    pub success: bool,
    pub feature_node_id: String,
    pub verification_score: f64,
    pub passed: bool,
    #[serde(default)]
    pub all_content: Option<std::collections::HashMap<String, String>>,
    pub error: Option<String>,
}

// ============================================================================
// Tauri Commands
// ============================================================================

#[tauri::command]
pub async fn get_dashboard_data(project_id: String) -> Result<DashboardData, String> {
    let client = reqwest::Client::new();
    let url = format!(
        "http://localhost:8000/api/v1/projects/{}/dashboard",
        project_id
    );

    let response = client
        .get(&url)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let data = response
        .json::<DashboardData>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(data)
}

#[tauri::command]
pub async fn get_feature_backlog(
    project_id: String,
    status: Option<String>,
    limit: Option<u32>,
) -> Result<Vec<FeatureBacklogItem>, String> {
    let client = reqwest::Client::new();
    let mut url = format!(
        "http://localhost:8000/api/v1/projects/{}/backlog",
        project_id
    );

    // Add query params
    let mut params = Vec::new();
    if let Some(s) = status {
        params.push(format!("status={}", s));
    }
    if let Some(l) = limit {
        params.push(format!("limit={}", l));
    }

    if !params.is_empty() {
        url.push('?');
        url.push_str(&params.join("&"));
    }

    let response = client
        .get(&url)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let data = response
        .json::<Vec<FeatureBacklogItem>>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(data)
}

#[tauri::command]
pub async fn get_graph_data(
    project_id: String,
    max_nodes: Option<u32>,
) -> Result<GraphData, String> {
    let client = reqwest::Client::new();
    let mut url = format!(
        "http://localhost:8000/api/v1/projects/{}/graph",
        project_id
    );

    if let Some(max) = max_nodes {
        url.push_str(&format!("?max_nodes={}", max));
    }

    let response = client
        .get(&url)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let data = response
        .json::<GraphData>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(data)
}

#[tauri::command]
pub async fn start_wizard(
    project_id: String,
    feature_title: String,
    feature_description: String,
) -> Result<WizardStartResult, String> {
    let client = reqwest::Client::new();
    let url = format!(
        "http://localhost:8000/api/v1/projects/{}/wizard/start",
        project_id
    );

    let payload = serde_json::json!({
        "title": feature_title,
        "description": feature_description,
    });

    let response = client
        .post(&url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let result = response
        .json::<WizardStartResult>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(result)
}

#[tauri::command]
pub async fn execute_wizard_step(
    session_id: String,
    user_edit: Option<String>,
    force: Option<bool>,
) -> Result<WizardStepResult, String> {
    let client = reqwest::Client::new();
    let url = format!(
        "http://localhost:8000/api/v1/wizard/{}/execute",
        session_id
    );

    let payload = serde_json::json!({
        "user_edit": user_edit,
        "force": force.unwrap_or(false),
    });

    let response = client
        .post(&url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(120))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let result = response
        .json::<WizardStepResult>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(result)
}

#[tauri::command]
pub async fn generate_yolo(
    project_id: String,
    feature_title: String,
    feature_description: String,
) -> Result<YoloGenerationResult, String> {
    let client = reqwest::Client::new();
    let url = format!(
        "http://localhost:8000/api/v1/projects/{}/yolo/generate",
        project_id
    );

    let payload = serde_json::json!({
        "title": feature_title,
        "description": feature_description,
    });

    let response = client
        .post(&url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(300))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    let result = response
        .json::<YoloGenerationResult>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    Ok(result)
}

#[tauri::command]
pub async fn accept_yolo_generation(
    project_id: String,
    feature_node_id: String,
) -> Result<bool, String> {
    let client = reqwest::Client::new();
    let url = format!(
        "http://localhost:8000/api/v1/projects/{}/yolo/accept",
        project_id
    );

    let payload = serde_json::json!({
        "feature_node_id": feature_node_id,
    });

    let response = client
        .post(&url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;

    if !response.status().is_success() {
        return Err(format!("Backend returned status: {}", response.status()));
    }

    Ok(true)
}

// ============================================================================
// Settings & Model Management
// ============================================================================

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AppSettings {
    pub ollama_host: String,
    pub model: String,
    pub theme: String,
    pub verification_threshold: f64,
    pub app_version: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct SettingsUpdate {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ollama_host: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub theme: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub verification_threshold: Option<f64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ModelInfo {
    pub name: String,
    pub size: Option<u64>,
    pub parameter_size: Option<String>,
    pub family: Option<String>,
    pub modified_at: Option<String>,
    pub active: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SystemInfo {
    pub app_version: String,
    pub python_version: String,
    pub platform: String,
    pub ollama_host: String,
    pub ollama_reachable: bool,
    pub ollama_version: Option<String>,
    pub active_model: String,
}

async fn parse_json<T: for<'de> Deserialize<'de>>(response: reqwest::Response) -> Result<T, String> {
    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        return Err(format!("Backend error {}: {}", status, body));
    }
    response
        .json::<T>()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))
}

#[tauri::command]
pub async fn get_settings() -> Result<AppSettings, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{}/settings", API_BASE))
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn update_settings(update: SettingsUpdate) -> Result<AppSettings, String> {
    let client = reqwest::Client::new();
    let resp = client
        .put(format!("{}/settings", API_BASE))
        .json(&update)
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn list_models() -> Result<Vec<ModelInfo>, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{}/models", API_BASE))
        .timeout(std::time::Duration::from_secs(20))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn pull_model(name: String) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/models/pull", API_BASE))
        .json(&serde_json::json!({ "name": name }))
        .timeout(std::time::Duration::from_secs(1800))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn delete_model(name: String) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    let resp = client
        .delete(format!("{}/models/{}", API_BASE, name))
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn get_system_info() -> Result<SystemInfo, String> {
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{}/system/info", API_BASE))
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[tauri::command]
pub async fn create_feature(
    project_id: String,
    title: String,
    description: String,
    category: String,
    impact_score: u32,
    effort_score: u32,
    risk_score: u32,
) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    let payload = serde_json::json!({
        "title": title,
        "description": description,
        "category": category,
        "impact_score": impact_score,
        "effort_score": effort_score,
        "risk_score": risk_score,
    });
    let resp = client
        .post(format!("{}/projects/{}/backlog", API_BASE, project_id))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BulkIdea {
    pub title: String,
    #[serde(default)]
    pub description: String,
}

#[tauri::command]
pub async fn bulk_generate(
    project_id: String,
    ideas: Vec<BulkIdea>,
    concurrency: Option<u32>,
) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    let payload = serde_json::json!({
        "ideas": ideas,
        "concurrency": concurrency.unwrap_or(3),
    });
    let resp = client
        .post(format!("{}/projects/{}/bulk/generate", API_BASE, project_id))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(3600))
        .send()
        .await
        .map_err(|e| format!("Failed to connect to backend: {}", e))?;
    parse_json(resp).await
}
