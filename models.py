from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

class ColumnInfo(BaseModel):
    name: str
    description: Optional[str] = None
    data_type: Optional[str] = None
    meta: Dict = Field(default_factory=dict)

class NodeConfig(BaseModel):
    schema: Optional[str] = None
    database: Optional[str] = None

class NodePatch(BaseModel):
    name: str
    description: Optional[str] = None
    columns: Optional[Dict[str, ColumnInfo]] = None
    config: Optional[NodeConfig] = None

class TestMetadata(BaseModel):
    name: str
    kwargs: Dict[str, str]
    namespace: Optional[str] = None

class TestNode(BaseModel):
    test_metadata: TestMetadata
    column_name: Optional[str] = None
    refs: List[List[str]] = Field(default_factory=list)

class ManifestNode(BaseModel):
    name: str
    schema: str
    database: Optional[str] = None
    description: Optional[str] = None
    columns: Dict[str, ColumnInfo] = Field(default_factory=dict)
    refs: List[List[str]] = Field(default_factory=list)
    tests: List[TestNode] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)
    
class Manifest(BaseModel):
    nodes: Dict[str, ManifestNode]
    parent_map: Dict[str, List[str]]
    child_map: Dict[str, List[str]] 