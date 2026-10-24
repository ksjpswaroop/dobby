// Prevent window resizing issues
#![cfg_attr(
  all(not(debug_assertions), target_os = "windows"),
  windows_subsystem = "windows"
)]

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![
      get_dashboard_data,
      get_feature_backlog,
      get_graph_data,
      start_wizard,
      execute_wizard_step,
      generate_yolo,
      accept_yolo_generation,
      create_feature,
      bulk_generate,
      get_settings,
      update_settings,
      list_models,
      pull_model,
      delete_model,
      get_system_info,
    ])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}

mod commands;
use commands::*;
