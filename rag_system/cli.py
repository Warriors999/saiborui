
@cli.command("generate-storyboard")
@click.argument("script", type=click.Path(exists=True))
@click.argument("product")
@click.argument("persona", default="折腾到吐")
def generate_storyboard(script: str, product: str, persona: str):
    """From finalized .docx script → storyboard .xlsx + lighting SVGs."""
    from pathlib import Path
    from rag_system.generation.script_to_storyboard import storyboard_pipeline

    click.echo(f"Generating storyboard for: {product}")
    result = storyboard_pipeline(Path(script), product, persona)
    click.echo(f"Done: {result}")
