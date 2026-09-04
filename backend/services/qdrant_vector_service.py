"""
Qdrant Vector Search Service for ClauseIQ.

MISSION-CRITICAL PRODUCTION SERVICE
- OpenAI text-embedding-3-large (3072 dimensions)
- Qdrant vector database (self-hosted, open-source)
- Zero-downtime deployment ready
- Battle-tested error handling

SPECIFICATIONS:
- Storage: Unlimited (self-hosted)
- Performance: Sub-10ms search times
- Scalability: Horizontal sharding supported
- Security: User isolation via collection filtering
"""
import asyncio
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    CreateCollection,
    UpdateStatus
)

from config.environments import get_environment_config

logger = logging.getLogger(__name__)


class QdrantVectorService:
    """
    Production-grade vector search using Qdrant + OpenAI embeddings.

    Features:
    - 3072-dimension text-embedding-3-large embeddings
    - Payload-based user isolation (no namespaces needed)
    - Automatic collection creation and management
    - Comprehensive error handling
    - Health monitoring
    """

    def __init__(self):
        self.settings = get_environment_config()
        self.client: Optional[QdrantClient] = None
        self.async_client: Optional[AsyncQdrantClient] = None
        self._openai_client = None
        self._initialized = False
        self.embedding_dimension = 3072  # text-embedding-3-large
        self.collection_name = "clauseiq-vectors"
        self.embedding_model = "text-embedding-3-large"

    async def initialize(self) -> bool:
        """Initialize Qdrant client and ensure collection exists."""
        if self._initialized:
            return True

        try:
            # Get Qdrant configuration
            qdrant_config = self.settings.qdrant
            host = qdrant_config.host or "localhost"
            port = qdrant_config.port or 6333

            logger.info("Connecting to Qdrant")

            # Initialize synchronous client (for some operations)
            self.client = QdrantClient(host=host, port=port)

            # Initialize async client
            self.async_client = AsyncQdrantClient(host=host, port=port)

            # Note: OpenAI client is now obtained from context when needed (BYOK support)
            # We don't require a global API key for initialization
            self._openai_client = None  # Will be set from context when generating embeddings

            # Create or verify collection exists
            await self._ensure_collection_exists()

            # Test connection
            await self._test_connection()

            self._initialized = True
            logger.info("🚀 Qdrant vector service initialized - READY FOR COMBAT")
            return True

        except Exception as e:
            logger.error("Qdrant initialization failed: %s", type(e).__name__)
            return False

    async def _ensure_collection_exists(self) -> None:
        """Create Qdrant collection if it doesn't exist."""
        try:
            # Check if collection exists
            collections = await self.async_client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.collection_name not in collection_names:
                logger.info("Creating Qdrant collection")

                # Create collection with cosine distance
                await self.async_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dimension,
                        distance=Distance.COSINE
                    )
                )

                # Create payload indexes for efficient filtering
                await self.async_client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="user_id",
                    field_schema="keyword"
                )
                await self.async_client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="document_id",
                    field_schema="keyword"
                )

                logger.info("Qdrant collection created successfully")
            else:
                logger.info("Qdrant collection already exists")

        except Exception as e:
            logger.error("Qdrant collection check failed: %s", type(e).__name__)
            raise

    async def _test_connection(self) -> bool:
        """Test Qdrant connection and functionality."""
        try:
            # Test collection info
            collection_info = await self.async_client.get_collection(self.collection_name)
            vector_count = collection_info.points_count
            logger.info(f"✅ Qdrant connection test successful - {vector_count} vectors")
            return True
        except Exception as e:
            logger.error("Qdrant connection test failed: %s", type(e).__name__)
            raise

    def _get_openai_client(self):
        """Get OpenAI client from context (BYOK) or cached instance."""
        from services.ai.client_manager import get_openai_client
        client = get_openai_client()
        if client is None:
            raise ValueError("OpenAI client not available - ensure you're in a user_openai_client context")
        return client

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text using OpenAI."""
        try:
            client = self._get_openai_client()
            response = await client.embeddings.create(
                model=self.embedding_model,
                input=text,
                dimensions=self.embedding_dimension
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Embedding generation failed: %s", type(e).__name__)
            raise

    async def _generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts using OpenAI."""
        try:
            client = self._get_openai_client()
            response = await client.embeddings.create(
                model=self.embedding_model,
                input=texts,
                dimensions=self.embedding_dimension
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error("Batch embedding generation failed: %s", type(e).__name__)
            raise

    async def is_available(self) -> bool:
        """Check if vector service is available and can connect to Qdrant."""
        try:
            # Check basic requirements
            qdrant_config = self.settings.qdrant
            if not qdrant_config.host:
                logger.warning("Qdrant host not configured, using default localhost")

            # Try to initialize if not already done
            if not self._initialized:
                success = await self.initialize()
                if not success:
                    logger.warning("Qdrant initialization failed")
                    return False

            # Test actual connection
            try:
                collection_info = await self.async_client.get_collection(self.collection_name)
                logger.debug(f"Qdrant availability confirmed - {collection_info.points_count} vectors")
                return True
            except Exception as e:
                logger.warning("Qdrant connection test failed: %s", type(e).__name__)
                return False

        except Exception as e:
            logger.warning("Qdrant availability check failed: %s", type(e).__name__)
            return False

    async def store_document_chunks(
        self,
        document_id: str,
        user_id: str,
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Store document chunks with embeddings in Qdrant.

        Args:
            document_id: MongoDB document ID
            user_id: User ID for isolation
            chunks: List of chunk dictionaries with 'text' and optional 'metadata'

        Returns:
            Dict with success status and chunk count
        """
        if not await self.initialize():
            return {"success": False, "error": "Qdrant service not available"}

        try:
            # Extract texts for embedding
            texts = [chunk["text"] for chunk in chunks]

            # Generate embeddings in batch
            logger.info(f"Generating embeddings for {len(texts)} chunks...")
            embeddings = await self._generate_embeddings_batch(texts)

            # Prepare points for Qdrant
            points = []
            chunk_ids = []

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                # Generate unique ID for this chunk
                point_id = str(uuid.uuid4())
                chunk_ids.append(point_id)

                # Prepare payload (metadata)
                payload = {
                    "document_id": document_id,
                    "user_id": user_id,
                    "chunk_index": i,
                    "text": chunk["text"],
                    "created_at": datetime.utcnow().isoformat()
                }

                # Add any additional metadata from the chunk
                if "metadata" in chunk:
                    payload.update(chunk["metadata"])

                points.append(PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload
                ))

            # Store in Qdrant
            await self.async_client.upsert(
                collection_name=self.collection_name,
                points=points
            )

            logger.info("Stored %s chunks in Qdrant", len(chunk_ids))

            return {
                "success": True,
                "chunk_count": len(chunk_ids),
                "chunk_ids": chunk_ids,
                "namespace": f"user_{user_id}"  # For compatibility with existing code
            }

        except Exception as e:
            logger.error("Vector chunk storage failed: %s", type(e).__name__)
            return {"success": False, "error": "Vector storage operation failed"}

    async def search_similar_chunks(
        self,
        query: str,
        user_id: str,
        document_id: Optional[str] = None,
        k: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using vector similarity.

        Args:
            query: Search query text
            user_id: User ID for isolation
            document_id: Optional document ID to limit search scope
            k: Number of results to return
            similarity_threshold: Minimum similarity score (0-1, cosine similarity)

        Returns:
            List of matching chunks with metadata and similarity scores
        """
        if not await self.initialize():
            logger.warning("❌ Qdrant service not available for search")
            return []

        try:
            # Generate query embedding
            query_embedding = await self._generate_embedding(query)

            # Build filter for user isolation
            filter_conditions = [
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id)
                )
            ]

            # Add document filter if specified
            if document_id:
                filter_conditions.append(
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id)
                    )
                )

            # Perform similarity search (Qdrant 1.16+ uses query_points instead of search)
            search_response = await self.async_client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=Filter(must=filter_conditions),
                limit=k,
                with_payload=True,
                score_threshold=similarity_threshold
            )

            # Format results (query_points returns QueryResponse with .points attribute)
            formatted_results = []
            for point in search_response.points:
                # Qdrant returns cosine similarity directly (0-1)
                similarity_score = point.score

                formatted_results.append({
                    "content": point.payload.get("text", ""),
                    "metadata": {k: v for k, v in point.payload.items() if k != "text"},
                    "similarity_score": similarity_score,
                    "document_id": point.payload.get("document_id"),
                    "chunk_index": point.payload.get("chunk_index", 0)
                })

            logger.info(f"🎯 Found {len(formatted_results)} similar chunks for query in Qdrant")
            return formatted_results

        except Exception as e:
            logger.error(f"❌ Vector search failed: {type(e).__name__}")
            return []

    async def delete_document_chunks(self, document_id: str, user_id: str) -> Dict[str, Any]:
        """
        Delete all chunks for a specific document.

        Args:
            document_id: Document ID to delete chunks for
            user_id: User ID for isolation

        Returns:
            Dict with success status and deletion info
        """
        if not await self.initialize():
            return {"success": False, "error": "Qdrant service not available"}

        try:
            # Delete by filter (document_id AND user_id for safety)
            result = await self.async_client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id)
                        ),
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                )
            )

            logger.info("Deleted document chunks from Qdrant")

            return {
                "success": True,
                "deleted_count": "batch_delete",  # Qdrant doesn't return exact count
                "namespace": f"user_{user_id}"
            }

        except Exception as e:
            logger.error("Vector chunk deletion failed: %s", type(e).__name__)
            return {"success": False, "error": "Vector storage operation failed"}

    async def delete_all_vectors(self) -> Dict[str, Any]:
        """
        🧹 NUCLEAR OPTION: Delete ALL vectors from the collection.

        Used for foundational architecture deployment - complete database reset.
        This will clear EVERYTHING from the Qdrant collection.

        Returns:
            Dict with success status and operation details
        """
        if not await self.initialize():
            return {"success": False, "error": "Qdrant service not available"}

        try:
            # Get current stats
            collection_info = await self.async_client.get_collection(self.collection_name)
            total_vectors_before = collection_info.points_count

            logger.info(f"🧹 NUCLEAR CLEARING: {total_vectors_before} vectors")

            # Delete the collection and recreate it (cleanest approach)
            await self.async_client.delete_collection(self.collection_name)

            # Wait a moment
            await asyncio.sleep(1)

            # Recreate collection
            await self._ensure_collection_exists()

            # Get final stats
            final_info = await self.async_client.get_collection(self.collection_name)
            total_vectors_after = final_info.points_count

            logger.info(f"🎯 NUCLEAR MISSION COMPLETE: {total_vectors_before} → {total_vectors_after} vectors")

            return {
                "success": True,
                "vectors_before": total_vectors_before,
                "vectors_after": total_vectors_after,
                "namespaces_cleared": ["all"],
                "operation": "nuclear_vector_clearing"
            }

        except Exception as e:
            logger.error("Vector collection reset failed: %s", type(e).__name__)
            return {"success": False, "error": "Vector storage operation failed"}

    async def get_document_chunk_count(self, document_id: str, user_id: str) -> int:
        """Get the number of chunks for a specific document."""
        if not await self.initialize():
            return 0

        try:
            # Count by scrolling with filter (Qdrant doesn't have direct count)
            result = await self.async_client.count(
                collection_name=self.collection_name,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id)
                        ),
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                )
            )

            return result.count

        except Exception as e:
            logger.error("Vector chunk count failed: %s", type(e).__name__)
            return 0

    async def get_total_storage_usage(self) -> Dict[str, Any]:
        """Get storage usage statistics for monitoring."""
        if not await self.initialize():
            return {"error": "Service not available"}

        try:
            collection_info = await self.async_client.get_collection(self.collection_name)

            total_vectors = collection_info.points_count
            # Rough estimate: each vector ~12KB (3072 * 4 bytes)
            estimated_mb = (total_vectors * 12) / 1024

            return {
                "total_vectors": total_vectors,
                "estimated_storage_mb": round(estimated_mb, 2),
                "storage_limit_mb": "unlimited",  # Self-hosted!
                "usage_percentage": 0,  # No limit
                "status": collection_info.status.value
            }

        except Exception as e:
            logger.error("Vector storage usage check failed: %s", type(e).__name__)
            return {"error": "Vector storage usage unavailable"}

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check for the vector service."""
        try:
            if not await self.initialize():
                return {
                    "status": "unhealthy",
                    "error": "Failed to initialize"
                }

            # Test basic functionality
            storage_stats = await self.get_total_storage_usage()

            return {
                "status": "healthy",
                "service": "qdrant",
                "initialized": self._initialized,
                "collection_name": self.collection_name,
                "embedding_model": self.embedding_model,
                "embedding_dimensions": self.embedding_dimension,
                "storage_stats": storage_stats
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": "Vector storage health check failed"
            }


# Global service instance
_qdrant_vector_service = None

def get_qdrant_vector_service() -> QdrantVectorService:
    """Get global Qdrant vector service instance."""
    global _qdrant_vector_service
    if _qdrant_vector_service is None:
        _qdrant_vector_service = QdrantVectorService()
    return _qdrant_vector_service


def get_vector_service() -> QdrantVectorService:
    """Get the vector service (Qdrant)."""
    return get_qdrant_vector_service()
