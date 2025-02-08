import graphviz
from models import Manifest
import networkx as nx
from typing import Dict, Set, Tuple, List
from streamlit_agraph import agraph, Node, Edge, Config
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile
import os

def get_column_type(info: dict, test_relationships: Dict[str, str] = None) -> str:
    """Get the type of column (PK, FK, or regular)."""
    if info.meta and info.meta.get('is_key'):
        return '🔑 PK'  # Primary Key
    elif test_relationships and info.name in test_relationships:
        return '🔗 FK'  # Foreign Key
    return ''

def create_table_html(table_name: str, node: dict) -> str:
    """Create HTML representation of a table with all columns."""
    # Extract relationship tests to identify foreign keys
    test_relationships = {}
    if hasattr(node, 'tests'):
        for test in node.tests:
            if test.test_metadata.name == "relationships" and test.column_name:
                test_relationships[test.column_name] = test.test_metadata.kwargs.get('to', '')

    # Create HTML table using graphviz's HTML-like syntax
    html = [
        '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">',
        f'<TR><TD COLSPAN="3" BGCOLOR="#4A90E2"><FONT COLOR="white"><B>{table_name}</B></FONT></TD></TR>',
        f'<TR><TD COLSPAN="3" BGCOLOR="#4A90E2"><FONT COLOR="white" POINT-SIZE="10">{node.description or ""}</FONT></TD></TR>',
        '<TR BGCOLOR="#E3F2FD">',
        '<TD><B>Column</B></TD>',
        '<TD><B>Type</B></TD>',
        '<TD><B>Key</B></TD>',
        '</TR>'
    ]
    
    # Add columns
    for col_name, info in node.columns.items():
        col_type = get_column_type(info, test_relationships)
        data_type = info.data_type if info.data_type else 'unknown'
        
        html.append('<TR>')
        html.append(f'<TD ALIGN="LEFT" PORT="{col_name}">{col_name}</TD>')
        html.append(f'<TD ALIGN="LEFT">{data_type}</TD>')
        html.append(f'<TD ALIGN="CENTER">{col_type}</TD>')
        html.append('</TR>')
    
    html.append('</TABLE>>')
    return ''.join(html)

def extract_relationships(manifest: Manifest) -> Tuple[Dict[str, Set[str]], Dict[str, Dict[str, str]], List[Tuple]]:
    """Extract relationships between tables based on relationship tests."""
    relationships = {}
    relationship_labels = {}
    column_relationships = []
    
    for node_id, node in manifest.nodes.items():
        if not node_id.startswith('model.'):
            continue
            
        model_name = f"{node.schema}.{node.name}"
        if model_name not in relationships:
            relationships[model_name] = set()
            relationship_labels[model_name] = {}
        
        # Process relationship tests
        for test in node.tests:
            if test.test_metadata.name == "relationships":
                kwargs = test.test_metadata.kwargs
                if "to" in kwargs and "field" in kwargs:
                    # Extract the referenced model name from the ref function
                    to_ref = kwargs["to"]
                    if to_ref.startswith("ref('") and to_ref.endswith("')"):
                        # Extract model name from ref('model_name')
                        to_model = to_ref[5:-2]  # Remove ref(' and ')
                        to_model = f"{node.schema}.{to_model}"  # Assume same schema
                        from_field = test.column_name
                        to_field = kwargs["field"]
                        
                        relationships[model_name].add(to_model)
                        relationship_labels[model_name][to_model] = from_field
                        column_relationships.append((
                            (model_name, from_field),
                            (to_model, to_field)
                        ))
    
    return relationships, relationship_labels, column_relationships

def get_node_color(node: dict) -> str:
    """Get the color for a node based on its layer and type."""
    layer = node.meta.get('layer', '')
    dv_type = node.meta.get('dv_type', '')
    
    if layer == 'raw':
        return "#E0E0E0"  # Gray
    elif layer == 'staging':
        return "#FFFFFF"  # White
    elif layer == 'mart':
        return "#FFA726"  # Orange
    elif layer == 'core':
        if dv_type == 'hub':
            return "#64B5F6"  # Blue
        elif dv_type == 'link':
            return "#81C784"  # Green
        elif dv_type == 'satellite':
            return "#FFD54F"  # Yellow
    return "#E3F2FD"  # Default light blue

def create_interactive_erd(manifest: Manifest, selected_layers=None, filter_nodes=None):
    """Create an interactive ERD using streamlit-agraph."""
    nodes = []
    edges = []
    
    # Create layer groups if showing multiple layers
    if selected_layers and len(selected_layers) > 1:
        # Add group nodes for each layer
        layer_groups = {}
        for layer in selected_layers:
            group_id = f"group_{layer}"
            layer_groups[layer] = group_id
            nodes.append(Node(
                id=group_id,
                label=layer.upper(),
                size=1,  # Minimal size
                color="rgba(245, 245, 245, 0.3)",  # Very light gray with high transparency
                shape="box",
                borderWidth=1,
                font={'size': 14, 'color': '#999999', 'face': 'Arial'},
                margin=20,
                group=layer,
                fixed=True,
                physics=False
            ))
    
    # Create nodes for all dbt models in selected layers
    for node_id, node in manifest.nodes.items():
        if not node_id.startswith('model.'):
            continue
            
        model_name = f"{node.schema}.{node.name}"
        layer = node.meta.get('layer', '')
        
        # Skip if node's layer is not selected
        if selected_layers and layer not in selected_layers:
            continue
            
        # Skip if we're filtering nodes and this node is not in the filter
        if filter_nodes is not None and node_id not in filter_nodes:
            continue
            
        # Get node color based on layer and type
        node_color = get_node_color(node)
        
        # Create node with table information
        node_config = {
            'id': model_name,
            'label': model_name,
            'size': 75,
            'color': node_color,
            'shape': "box",
            'borderWidth': 2,
            'font': {'size': 16, 'color': 'black', 'face': 'Arial'},
            'margin': 20,
            'title': node.description or ""
        }
        
        # Add group information if showing multiple layers
        if selected_layers and len(selected_layers) > 1:
            node_config['group'] = layer
        
        nodes.append(Node(**node_config))
    
    # Create edges based on parent/child relationships
    for node_id, parents in manifest.parent_map.items():
        if not node_id.startswith('model.'):
            continue
            
        node = manifest.nodes.get(node_id)
        if not node or (selected_layers and node.meta.get('layer', '') not in selected_layers):
            continue
            
        # Skip if we're filtering nodes and this node is not in the filter
        if filter_nodes is not None and node_id not in filter_nodes:
            continue
            
        source_model = f"{node.schema}.{node.name}"
        
        for parent_id in parents:
            if not parent_id.startswith('model.'):
                continue
                
            parent_node = manifest.nodes.get(parent_id)
            if not parent_node or (selected_layers and parent_node.meta.get('layer', '') not in selected_layers):
                continue
                
            # Skip if we're filtering nodes and the parent node is not in the filter
            if filter_nodes is not None and parent_id not in filter_nodes:
                continue
                
            target_model = f"{parent_node.schema}.{parent_node.name}"
            
            edges.append(Edge(
                source=source_model,
                target=target_model,
                color="#4A90E2",
                width=2,
                arrows={"to": {"enabled": True}}
            ))
    
    # Configuration for the graph
    config = Config(
        width=1500,
        height=1000,
        directed=True,
        physics={
            "enabled": True,
            "hierarchicalRepulsion": {
                "centralGravity": 0.1,
                "springLength": 400,
                "springConstant": 0.5,
                "nodeDistance": 400,
                "damping": 0.09
            },
            "solver": "hierarchicalRepulsion",
            "stabilization": {
                "enabled": True,
                "iterations": 2000,
                "updateInterval": 50,
                "fit": True
            }
        },
        hierarchical={
            "enabled": True,
            "levelSeparation": 400,
            "nodeSpacing": 400,
            "direction": "LR",
            "sortMethod": "directed",
            "shakeTowards": "leaves",
            "blockShifting": True,
            "edgeMinimization": True,
            "parentCentralization": True
        },
        groups={
            'raw': {'color': {'background': 'rgba(245, 245, 245, 0.2)', 'border': 'rgba(224, 224, 224, 0.3)'}},
            'staging': {'color': {'background': 'rgba(245, 245, 245, 0.2)', 'border': 'rgba(224, 224, 224, 0.3)'}},
            'core': {'color': {'background': 'rgba(245, 245, 245, 0.2)', 'border': 'rgba(224, 224, 224, 0.3)'}},
            'mart': {'color': {'background': 'rgba(245, 245, 245, 0.2)', 'border': 'rgba(224, 224, 224, 0.3)'}}
        },
        nodeHighlightBehavior=True,
        highlightColor="#F7A7A6",
        node={
            'labelProperty': 'label',
            'renderLabel': True,
            'font': {'size': 16, 'color': 'black', 'face': 'Arial'},
            'widthConstraint': {'minimum': 200, 'maximum': 400},
            'margin': 20,
            'shadow': True,
            'fixed': {
                'x': False,
                'y': False
            }
        },
        events={
            'click': True,
            'background': True
        }
    )
    
    return nodes, edges, config

def create_erd(manifest: Manifest) -> graphviz.Digraph:
    """Create a static ERD diagram using graphviz (for PDF export)."""
    dot = graphviz.Digraph(comment='DBT ERD', format='pdf')
    dot.attr(rankdir='LR', nodesep='1.0', ranksep='2.0', splines='ortho')
    dot.attr('node', shape='plain', style='filled', fillcolor='#E8F4F9')
    
    # Add nodes (tables)
    for node_id, node in manifest.nodes.items():
        if not node_id.startswith('model.'):
            continue
            
        model_name = f"{node.schema}.{node.name}"
        
        # Start HTML table
        table_html = [
            '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">',
            f'<TR><TD PORT="header" BGCOLOR="#4A90E2" COLSPAN="3"><FONT COLOR="white"><B>{model_name}</B></FONT></TD></TR>',
            '<TR><TD BGCOLOR="#E3F2FD"><B>Column</B></TD><TD BGCOLOR="#E3F2FD"><B>Type</B></TD><TD BGCOLOR="#E3F2FD"><B>Key</B></TD></TR>'
        ]
        
        # Add columns
        for col_name, info in node.columns.items():
            col_type = get_column_type(info)
            key_indicator = col_type if col_type else ""
            
            table_html.append(
                f'<TR><TD PORT="{col_name}" ALIGN="LEFT">{col_name}</TD>'
                f'<TD ALIGN="LEFT">{info.data_type or "unknown"}</TD>'
                f'<TD ALIGN="CENTER">{key_indicator}</TD></TR>'
            )
        
        table_html.append('</TABLE>>')
        dot.node(model_name, ''.join(table_html))
    
    # Add edges for relationships
    _, _, column_relationships = extract_relationships(manifest)
    
    for (source_table, source_col), (target_table, target_col) in column_relationships:
        dot.edge(
            f'{source_table}:{source_col}',
            f'{target_table}:{target_col}',
            dir='both',
            arrowhead='crow',
            arrowtail='none',
            color='#4A90E2',
            penwidth='1.5'
        )
    
    return dot 

def create_pyvis_erd(manifest: Manifest, selected_layers=None):
    """Create an interactive ERD using Pyvis."""
    # Create a network
    net = Network(
        height="1000px",
        width="100%",
        bgcolor="#ffffff",
        font_color="black",
        directed=True
    )
    
    # Configure physics
    net.force_atlas_2based(
        gravity=-50,
        central_gravity=0.01,
        spring_length=200,
        spring_strength=0.08,
        damping=0.4,
        overlap=0
    )
    
    # Create nodes for all dbt models in selected layers
    for node_id, node in manifest.nodes.items():
        if not node_id.startswith('model.'):
            continue
            
        model_name = f"{node.schema}.{node.name}"
        layer = node.meta.get('layer', '')
        
        # Skip if node's layer is not selected
        if selected_layers and layer not in selected_layers:
            continue
            
        # Get node color based on layer and type
        node_color = get_node_color(node)
        
        # Add node with table information
        net.add_node(
            model_name,
            label=model_name,
            title=node.description or "",
            color=node_color,
            shape="box",
            size=50,
            font={'size': 16},
            borderWidth=2,
            shadow=True
        )
    
    # Add edges based on parent/child relationships
    for node_id, parents in manifest.parent_map.items():
        if not node_id.startswith('model.'):
            continue
            
        node = manifest.nodes.get(node_id)
        if not node or (selected_layers and node.meta.get('layer', '') not in selected_layers):
            continue
            
        source_model = f"{node.schema}.{node.name}"
        
        for parent_id in parents:
            if not parent_id.startswith('model.'):
                continue
                
            parent_node = manifest.nodes.get(parent_id)
            if not parent_node or (selected_layers and parent_node.meta.get('layer', '') not in selected_layers):
                continue
                
            target_model = f"{parent_node.schema}.{parent_node.name}"
            
            net.add_edge(
                source=source_model,
                to=target_model,
                color="#4A90E2",
                width=2,
                arrows={'to': {'enabled': True}}
            )
    
    # Set layout options
    net.set_options("""
    {
        "layout": {
            "hierarchical": {
                "enabled": true,
                "direction": "LR",
                "sortMethod": "directed",
                "nodeSpacing": 200,
                "levelSeparation": 300,
                "blockShifting": true,
                "edgeMinimization": true,
                "parentCentralization": true
            }
        },
        "physics": {
            "hierarchicalRepulsion": {
                "centralGravity": 0,
                "springLength": 300,
                "springConstant": 0.8,
                "nodeDistance": 250,
                "damping": 0.09
            },
            "minVelocity": 0.75,
            "solver": "hierarchicalRepulsion"
        },
        "interaction": {
            "navigationButtons": true,
            "keyboard": true,
            "hover": true
        }
    }
    """)
    
    # Generate HTML file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html') as tmp_file:
        net.save_graph(tmp_file.name)
        return tmp_file.name 

def create_networkx_erd(manifest: Manifest, selected_layers=None):
    """Create an interactive ERD using NetworkX with Graphviz layout."""
    G = nx.DiGraph()
    
    # Add nodes
    for node_id, node in manifest.nodes.items():
        if not node_id.startswith('model.'):
            continue
            
        model_name = f"{node.schema}.{node.name}"
        layer = node.meta.get('layer', '')
        
        # Skip if node's layer is not selected
        if selected_layers and layer not in selected_layers:
            continue
            
        # Get node color based on layer and type
        node_color = get_node_color(node)
        
        # Add node with attributes
        G.add_node(
            model_name,
            label=model_name,
            color=node_color,
            title=node.description or "",
            layer=layer
        )
    
    # Add edges
    for node_id, parents in manifest.parent_map.items():
        if not node_id.startswith('model.'):
            continue
            
        node = manifest.nodes.get(node_id)
        if not node or (selected_layers and node.meta.get('layer', '') not in selected_layers):
            continue
            
        source_model = f"{node.schema}.{node.name}"
        
        for parent_id in parents:
            if not parent_id.startswith('model.'):
                continue
                
            parent_node = manifest.nodes.get(parent_id)
            if not parent_node or (selected_layers and parent_node.meta.get('layer', '') not in selected_layers):
                continue
                
            target_model = f"{parent_node.schema}.{parent_node.name}"
            G.add_edge(source_model, target_model)
    
    # Use graphviz layout for better node positioning
    pos = nx.nx_agraph.graphviz_layout(G, prog='dot', args='-Grankdir=LR -Gnodesep=1.0 -Granksep=2.0')
    
    # Convert to agraph nodes and edges
    nodes = []
    edges = []
    
    for node, (x, y) in pos.items():
        node_data = G.nodes[node]
        nodes.append(Node(
            id=node,
            label=node_data['label'],
            size=75,
            color=node_data['color'],
            shape="box",
            borderWidth=2,
            font={'size': 16, 'color': 'black', 'face': 'Arial'},
            margin=20,
            title=node_data['title'],
            x=x * 0.5,  # Scale positions to fit better
            y=y * 0.5
        ))
    
    for source, target in G.edges():
        edges.append(Edge(
            source=source,
            target=target,
            color="#4A90E2",
            width=2,
            arrows={"to": {"enabled": True}}
        ))
    
    # Configuration for the graph
    config = Config(
        width=1500,
        height=1000,
        directed=True,
        physics={
            "enabled": False  # Disable physics to maintain Graphviz layout
        },
        hierarchical={
            "enabled": False  # Use the pre-computed Graphviz layout instead
        },
        nodeHighlightBehavior=True,
        highlightColor="#F7A7A6",
        node={
            'labelProperty': 'label',
            'renderLabel': True,
            'font': {'size': 16, 'color': 'black', 'face': 'Arial'},
            'widthConstraint': {'minimum': 200, 'maximum': 400},
            'margin': 20,
            'shadow': True,
            'fixed': {
                'x': True,
                'y': True
            }
        }
    )
    
    return nodes, edges, config 