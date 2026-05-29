import os

file_path = r'c:\Users\ssakesh\Downloads\DHARA-GX\Agent Dhara Backend\agent\etl_pipeline\sql_codegen.py'

# Reset file to original before refactoring
os.system('git checkout agent/etl_pipeline/sql_codegen.py')

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Inject _get_transformed_table_name helper
clean_tbl_return = 'return f"{schema}.{clean_tbl}"'
transformed_helper = '''return f"{schema}.{clean_tbl}"


def _get_transformed_table_name(ds_name: str) -> str:
    """Resolve raw table name to its transformed table equivalent."""
    parts = ds_name.split(".", 1)
    if len(parts) == 2:
        schema, tbl_name = parts[0], parts[1]
    else:
        schema, tbl_name = "dbo", ds_name
    
    schema = schema.strip("[]")
    tbl_name = tbl_name.strip("[]")
    
    if tbl_name.lower().endswith("_raw"):
        trans_tbl = tbl_name[:-4] + "_Transformed"
    elif tbl_name.lower().endswith("_clean"):
        trans_tbl = tbl_name[:-6] + "_Transformed"
    else:
        trans_tbl = tbl_name + "_Transformed"
        
    return f"{schema}.{trans_tbl}"'''

if clean_tbl_return in content:
    content = content.replace(clean_tbl_return, transformed_helper, 1)
else:
    print("Warning: _get_clean_table_name return pattern not found!")

lines = content.splitlines()

# 1. Find the dataset loop start line
loop_start = -1
for i, line in enumerate(lines):
    if line.strip() == 'for ds_name, block in ds_plan.items():':
        loop_start = i
        break

if loop_start == -1:
    print("Error: Could not find loop start line!")
    exit(1)

# 2. Find the loop end line
loop_end = -1
for i in range(loop_start, len(lines)):
    if "Generate master orchestrator procedure for T-SQL" in lines[i]:
        loop_end = i
        break

if loop_end == -1:
    print("Error: Could not find loop end line!")
    exit(1)

print(f"Loop starts at line {loop_start+1}, ends at line {loop_end+1}")

original_body = lines[loop_start+1:loop_end]

new_body = []
new_body.append('    generation_mode = str(plan.get("generation_mode") or "full").lower()')
new_body.append('')
new_body.append('    for ds_name, block in ds_plan.items():')
new_body.append('        tbl_base = ds_name.split(".")[-1].strip("[]")')
new_body.append('        tbl_clean = _get_clean_table_name(ds_name)')
new_body.append('        tbl_transformed = _get_transformed_table_name(ds_name)')
new_body.append('        ')
new_body.append('        phases_to_gen = []')
new_body.append('        if generation_mode in ("cleanse_only", "full"):')
new_body.append('            phases_to_gen.append("clean")')
new_body.append('        if generation_mode in ("transform_only", "full"):')
new_body.append('            phases_to_gen.append("transform")')
new_body.append('            ')
new_body.append('        for ph in phases_to_gen:')
new_body.append('            is_clean = (ph == "clean")')
new_body.append('            sp_name = f"etl_clean_{tbl_base}" if is_clean else f"etl_transform_{tbl_base}"')
new_body.append('            ')
new_body.append('            src_tbl_expr = tsql_qualified_name(ds_name) if is_clean else tsql_qualified_name(tbl_clean)')
new_body.append('            tgt_tbl_expr = tsql_qualified_name(tbl_clean) if is_clean else tsql_qualified_name(tbl_transformed)')
new_body.append('            if dialect != "tsql":')
new_body.append('                src_tbl_expr = _brk(ds_name) if is_clean else _brk(tbl_clean)')
new_body.append('                tgt_tbl_expr = _brk(tbl_clean) if is_clean else _brk(tbl_transformed)')
new_body.append('                ')
new_body.append('            target_tbl_str = tbl_clean if is_clean else tbl_transformed')
new_body.append('            raw_tbl = src_tbl_expr')
new_body.append('            clean_tbl = tgt_tbl_expr')
new_body.append('            tbl_clean = target_tbl_str')
new_body.append('            tbl_staging = f"#{tbl_base}_Staging" if is_clean else f"#{tbl_base}_Transform_Staging"')

# Process each original body line
for i, line in enumerate(original_body):
    # Skip original raw_tbl, clean_tbl, tbl_staging assignments
    if 'raw_tbl = tsql_qualified_name(ds_name)' in line:
        continue
    if 'clean_tbl = tsql_qualified_name(tbl_clean)' in line:
        continue
    if 'tbl_staging = f"#{tbl_base}_Staging"' in line:
        continue
        
    # Replace step filtering/loop
    if 'for st in (block.get("steps") or []):' in line:
        line = line.replace('for st in (block.get("steps") or []):', 'for st in steps_phase:')
        
    # Inject steps_phase filtering right before step filtering
    if '# Consolidate, filter, and sort steps for this dataset' in line:
        new_body.append(' ' * 12 + '# Filter steps for current phase')
        new_body.append(' ' * 12 + 'from agent.etl_pipeline.phase_classifier import classify_action_phase')
        new_body.append(' ' * 12 + 'steps_raw = block.get("steps") or []')
        new_body.append(' ' * 12 + 'steps_phase = []')
        new_body.append(' ' * 12 + 'for st in steps_raw:')
        new_body.append(' ' * 12 + '    act_phase = classify_action_phase(st.get("action"))')
        new_body.append(' ' * 12 + '    if is_clean and act_phase == "cleanse":')
        new_body.append(' ' * 12 + '        steps_phase.append(st)')
        new_body.append(' ' * 12 + '    elif not is_clean and act_phase == "transform":')
        new_body.append(' ' * 12 + '        steps_phase.append(st)')
        new_body.append('')
        
    # Replace local_excluded_columns scan to run on overall block.get("steps") instead of phase-filtered steps
    if 'for st in steps:' in line and i > 0 and 'skipped_comments = []' in original_body[i-1]:
        line = line.replace('for st in steps:', 'for st in (block.get("steps") or []):')
        
    # Replace stored procedure drop check and name
    line = line.replace("etl_clean_{tbl_base}", "{sp_name}")
    
    # Wrap primary key validation
    if 'if pk_col and dialect == "tsql" and not never_drop:' in line:
        line = line.replace('if pk_col and dialect == "tsql" and not never_drop:', 'if is_clean and pk_col and dialect == "tsql" and not never_drop:')
        
    # Wrap numeric ID validations
    if 'if dialect == "tsql":' in line and 'Reject non-numeric IDs and decimals/floats' in line:
        line = line.replace('if dialect == "tsql":', 'if is_clean and dialect == "tsql":')
        
    # Add 4 spaces of indentation to all lines of the loop body (making original 8 spaces become 12 spaces)
    if line.strip():
        new_body.append(' ' * 4 + line)
    else:
        new_body.append(line)

# Let's adjust the non-nullable loop indentation in new_body
nn_loop_idx = -1
for i, line in enumerate(new_body):
    if 'for nn_col in non_nullable_cols:' in line:
        nn_loop_idx = i
        break

if nn_loop_idx != -1:
    indent = len(new_body[nn_loop_idx]) - len(new_body[nn_loop_idx].lstrip())
    new_body.insert(nn_loop_idx, ' ' * indent + 'if is_clean:')
    # Indent the loop and its body by 4 extra spaces
    for j in range(nn_loop_idx + 1, len(new_body)):
        if 'for st in steps:' in new_body[j] or 'for st in steps_phase:' in new_body[j]:
            break
        if new_body[j].strip():
            new_body[j] = ' ' * 4 + new_body[j]

# Reassemble the file
updated_lines = lines[:loop_start] + new_body + lines[loop_end:]

# Now, let's locate the etl_main proc execution logic and replace it
main_start = -1
for i, line in enumerate(updated_lines):
    if "# Execute each clean stored procedure" in line:
        main_start = i
        break

if main_start != -1:
    # Find the end of this block
    main_end = -1
    for i in range(main_start, len(updated_lines)):
        if "Update master process watermark" in updated_lines[i] or "Update process watermark" in updated_lines[i]:
            main_end = i
            break
            
    if main_end != -1:
        # We replace from main_start to main_end-1
        replacement = [
            "        # Execute procedures based on generation_mode",
            "        for ds_name in ds_plan.keys():",
            "            tbl_base = ds_name.split('.')[-1].strip('[]')",
            "            if generation_mode in ('cleanse_only', 'full'):",
            "                lines.append(f'        EXEC dbo.etl_clean_{tbl_base} @load_type = @load_type, @last_run = @last_run;')",
            "            ",
            "            if generation_mode in ('transform_only', 'full'):",
            "                from agent.etl_pipeline.dq_gate import check_dq_gate",
            "                threshold = float(business_rules.get('dq_threshold', 70.0))",
            "                gate_res = check_dq_gate(assessment, ds_name, threshold=threshold)",
            "                if generation_mode == 'transform_only' or gate_res['passed']:",
            "                    lines.append(f'        EXEC dbo.etl_transform_{tbl_base} @load_type = @load_type, @last_run = @last_run;')",
            "                else:",
            "                    lines.append(f\"        -- \u26a0 Phase 2 transform blocked: dataset '{ds_name}' did not pass the DQ gate (Score: {gate_res['score']} < {threshold})\")",
            ""
        ]
        updated_lines = updated_lines[:main_start] + replacement + updated_lines[main_end:]

# Update the master watermark line
for i, line in enumerate(updated_lines):
    if "master_wm = \"COALESCE((SELECT MAX(last_run_time) FROM dbo.etl_watermark WHERE process_name LIKE 'etl_clean_%'), GETDATE())\"" in line:
        updated_lines[i] = line.replace("'etl_clean_%'", "'etl_clean_%' OR process_name LIKE 'etl_transform_%'")
        break

with open(file_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(updated_lines) + '\n')

print("Successfully refactored sql_codegen.py!")
