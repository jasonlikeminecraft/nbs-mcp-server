from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise RuntimeError("The mcp package is required. Install dependencies with: pip install -r requirements.txt") from exc

from nbs_tools import (
    add_notes,
    analyze_music,
    apply_note_patch,
    arrange_song,
    change_tempo,
    compare_nbs,
    copy_range,
    create_blank_nbs,
    create_nbs_from_notes,
    crop_nbs,
    dedupe_notes,
    describe_layer_roles,
    export_command_blocks,
    export_markdown_summary,
    export_midi,
    export_note_table,
    fade_velocity,
    generate_bassline,
    generate_chord_progression,
    generate_drum_pattern,
    generate_melody,
    generate_simple_song,
    get_nbs_info,
    get_editable_regions,
    humanize_nbs,
    import_midi,
    import_note_table,
    make_loop,
    merge_nbs,
    normalize_layers,
    quantize_nbs,
    read_nbs_notes,
    reharmonize_nbs,
    remove_notes,
    render_preview,
    repair_nbs,
    scale_velocity,
    set_layer_metadata,
    split_layers,
    suggest_edits,
    summarize_nbs,
    transpose_nbs,
    validate_nbs,
    shift_ticks,
)


mcp = FastMCP("nbs-mcp-server")


mcp.tool()(get_nbs_info)
mcp.tool()(read_nbs_notes)
mcp.tool()(summarize_nbs)
mcp.tool()(analyze_music)
mcp.tool()(describe_layer_roles)
mcp.tool()(get_editable_regions)
mcp.tool()(create_blank_nbs)
mcp.tool()(create_nbs_from_notes)
mcp.tool()(add_notes)
mcp.tool()(remove_notes)
mcp.tool()(transpose_nbs)
mcp.tool()(change_tempo)
mcp.tool()(shift_ticks)
mcp.tool()(copy_range)
mcp.tool()(quantize_nbs)
mcp.tool()(scale_velocity)
mcp.tool()(fade_velocity)
mcp.tool()(humanize_nbs)
mcp.tool()(set_layer_metadata)
mcp.tool()(normalize_layers)
mcp.tool()(dedupe_notes)
mcp.tool()(crop_nbs)
mcp.tool()(repair_nbs)
mcp.tool()(apply_note_patch)
mcp.tool()(suggest_edits)
mcp.tool()(export_note_table)
mcp.tool()(import_note_table)
mcp.tool()(export_midi)
mcp.tool()(import_midi)
mcp.tool()(render_preview)
mcp.tool()(export_markdown_summary)
mcp.tool()(export_command_blocks)
mcp.tool()(split_layers)
mcp.tool()(merge_nbs)
mcp.tool()(compare_nbs)
mcp.tool()(validate_nbs)
mcp.tool()(generate_simple_song)
mcp.tool()(generate_melody)
mcp.tool()(generate_chord_progression)
mcp.tool()(generate_bassline)
mcp.tool()(generate_drum_pattern)
mcp.tool()(reharmonize_nbs)
mcp.tool()(make_loop)
mcp.tool()(arrange_song)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
