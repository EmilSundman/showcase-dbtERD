import streamlit as st
import json
from models import Manifest
from erd_generator import create_erd, create_interactive_erd
import tempfile
import os
import pathlib
import pandas as pd
from streamlit_agraph import agraph

st.set_page_config(
    page_title="DBT ERD Viewer",
    page_icon="🔍",
    layout="wide"
)

def get_connected_nodes(manifest, selected_node_id):
    """Get all nodes connected to the selected node (parents and children)."""
    connected_nodes = set()
    if selected_node_id:
        # Add the selected node
        connected_nodes.add(selected_node_id)
        # Add parent nodes
        parents = manifest.parent_map.get(selected_node_id, [])
        connected_nodes.update(parents)
        # Add child nodes
        children = manifest.child_map.get(selected_node_id, [])
        connected_nodes.update(children)
    return connected_nodes

def create_column_dataframe(node):
    """Create a DataFrame from node columns."""
    data = []
    for col_name, info in node.columns.items():
        data.append({
            'Column': col_name,
            'Type': info.data_type or 'unknown',
            'Description': info.description or '',
            'Key': 'PK' if info.meta.get('is_key') else ('FK' if info.meta.get('is_foreign_key') else ''),
            'References': f"{info.meta.get('references', '')}.{info.meta.get('references_field', '')}" if info.meta.get('is_foreign_key') else ''
        })
    return pd.DataFrame(data)

def display_model_details(manifest, selected_model):
    """Display details for the selected model."""
    # Find the actual node ID from the selected model name
    selected_node_id = None
    for node_id, node in manifest.nodes.items():
        if node_id.startswith('model.') and f"{node.schema}.{node.name}" == selected_model:
            selected_node_id = node_id
            break
    
    if selected_node_id and selected_node_id in manifest.nodes:
        node = manifest.nodes[selected_node_id]
        st.markdown(f"### {node.schema}.{node.name}")
        
        # Show table metadata
        with st.expander("Table Metadata", expanded=True):
            st.write(f"**Description:** {node.description or 'No description available'}")
            st.write(f"**Database:** {node.database or 'Default'}")
            st.write(f"**Schema:** {node.schema}")
            if node.meta:
                st.write("**Metadata:**")
                st.json(node.meta)
        
        # Show column information
        st.markdown("### Columns")
        df = create_column_dataframe(node)
        st.dataframe(
            df,
            column_config={
                "Column": st.column_config.TextColumn("Column", width="medium"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Key": st.column_config.TextColumn("Key", width="small"),
                "References": st.column_config.TextColumn("References", width="medium")
            },
            hide_index=True,
            use_container_width=True
        )
        
        # Show relationships
        with st.expander("Relationships", expanded=True):
            incoming = manifest.parent_map.get(selected_node_id, [])
            outgoing = manifest.child_map.get(selected_node_id, [])
            
            if incoming:
                st.markdown("**Referenced by:**")
                for ref in incoming:
                    ref_node = manifest.nodes.get(ref)
                    if ref_node:
                        st.write(f"- {ref_node.schema}.{ref_node.name}")
            
            if outgoing:
                st.markdown("**References:**")
                for ref in outgoing:
                    ref_node = manifest.nodes.get(ref)
                    if ref_node:
                        st.write(f"- {ref_node.schema}.{ref_node.name}")

st.title("DBT ERD Viewer")
st.markdown("""
Upload your dbt manifest.json file to generate an interactive ERD diagram.
The diagram will show relationships between your models based on refs and relationship tests.
""")

# Add option to use example manifest
use_example = st.checkbox("Use example manifest", help="Use a sample manifest.json file to explore the features")

# File uploader (only show if not using example)
if not use_example:
    uploaded_file = st.file_uploader("Upload your manifest.json file", type=['json'])
else:
    uploaded_file = None
    st.info("Using example manifest file with a simple e-commerce data model")

try:
    # Load manifest data
    if uploaded_file is not None:
        manifest_data = json.load(uploaded_file)
    elif use_example:
        with open('manifest_example.json', 'r') as f:
            manifest_data = json.load(f)
    else:
        st.info("Please upload a manifest.json file or use the example to begin")
        st.stop()
    
    # Create manifest object
    manifest = Manifest(
        nodes=manifest_data.get('nodes', {}),
        parent_map=manifest_data.get('parent_map', {}),
        child_map=manifest_data.get('child_map', {})
    )
    
    # Initialize session state for selected model if not exists
    if 'selected_model' not in st.session_state:
        st.session_state['selected_model'] = None
    
    # Create columns for layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Create a horizontal layout for controls
        controls_col1, controls_col2, controls_col3 = st.columns([3, 1, 1])
        
        with controls_col1:
            # Add layer filter
            available_layers = {
                'raw': 'Raw Layer',
                'staging': 'Staging Layer',
                'core': 'Data Vault Core',
                'mart': 'Mart Layer'
            }
            
            # Add "Show All" option at the top
            show_all = st.checkbox("Show All Layers", value=False)
            
            if show_all:
                selected_layers = list(available_layers.keys())
            else:
                selected_layer = st.radio(
                    "Select layer:",
                    options=list(available_layers.keys()),
                    format_func=lambda x: available_layers[x],
                    horizontal=True
                )
                selected_layers = [selected_layer]
        
        with controls_col2:
            # Add download button
            if st.button("📥 Download PDF"):
                # Create static ERD for PDF export
                dot = create_erd(manifest)
                
                # Create a temporary directory that will be cleaned up automatically
                with tempfile.TemporaryDirectory() as tmp_dir:
                    # Create full paths for our files
                    tmp_path = pathlib.Path(tmp_dir)
                    pdf_path = tmp_path / "erd_diagram.pdf"
                    
                    # Render the graph
                    dot.render(pdf_path, format='pdf', cleanup=True)
                    
                    # Add download button for PDF
                    with open(f"{pdf_path}.pdf", "rb") as pdf_file:
                        pdf_bytes = pdf_file.read()
                        st.download_button(
                            label="Save PDF",
                            data=pdf_bytes,
                            file_name="dbt_erd.pdf",
                            mime="application/pdf"
                        )
        
        with controls_col3:
            # Add clear selection button
            if st.button("🔄 Clear Selection"):
                st.session_state['selected_model'] = None
                st.rerun()
        
        # Create container for the graph
        graph_container = st.container()
        
        with graph_container:
            # Get the current selected model's node ID
            current_model = st.session_state.get('selected_model')
            selected_node_id = None
            if current_model:
                for node_id, node in manifest.nodes.items():
                    if node_id.startswith('model.') and f"{node.schema}.{node.name}" == current_model:
                        selected_node_id = node_id
                        break
            
            # Get connected nodes if a node is selected
            connected_nodes = get_connected_nodes(manifest, selected_node_id) if selected_node_id else set()
            
            # Show graph for selected layer
            nodes, edges, config = create_interactive_erd(
                manifest, 
                selected_layers,
                filter_nodes=connected_nodes if connected_nodes else None
            )
            
            clicked = agraph(
                nodes=nodes,
                edges=edges,
                config=config
            )
            
            # Update selected model based on clicked node or clear if background clicked
            if clicked == "background":
                st.session_state['selected_model'] = None
                st.rerun()
            elif clicked:
                st.session_state['selected_model'] = clicked
                st.rerun()
    
    with col2:
        st.subheader("Model Details")
        current_model = st.session_state.get('selected_model')
        if current_model:
            display_model_details(manifest, current_model)
        else:
            st.info("Select a model to view its details")
                        
except Exception as e:
    st.error(f"Error processing manifest file: {str(e)}")
    # Add more detailed error information in an expander
    with st.expander("Error Details"):
        st.exception(e) 