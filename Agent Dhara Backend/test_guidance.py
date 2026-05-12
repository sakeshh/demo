from agent.specialists.etl_guidance_specialist import format_etl_guidance

assessment = {
    "data_quality_issues": {
        "datasets": {
            "my_data.csv": {
                "issues": [
                    {"column": "email", "type": "invalid_email"}
                ]
            }
        }
    }
}
context = {
    "selected_blob_files": ["my_data.csv"]
}
print(format_etl_guidance(assessment, context=context))
