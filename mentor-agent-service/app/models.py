from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(Text)
    current_context = Column(Text)
    skill_level = Column(Text)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=True)


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    source_material = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Concept(Base):
    __tablename__ = "concepts"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    name = Column(Text, nullable=False)
    definition = Column(Text, nullable=True)
    difficulty = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ConceptEdge(Base):
    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint("source_concept_id", "target_concept_id", "relationship_type"),
    )

    id = Column(Integer, primary_key=True)
    source_concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=False)
    target_concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=False)
    relationship_type = Column(Text, nullable=False)
    weight = Column(Float, server_default="1.0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
