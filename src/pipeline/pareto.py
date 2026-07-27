"""
Pareto Scorer for Dobby v2.0

Automatic feature prioritization using Pareto scoring:
- Score = (Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)
- Daily re-scoring based on learning
- Sort features by priority
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import structlog

from src.db.schema import DatabaseManager, FeatureBacklog

logger = structlog.get_logger()


# ============================================================================
# Pareto Scorer
# ============================================================================
class ParetoScorer:
    """
    Pareto scorer for feature prioritization
    
    Formula: Score = (Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)
    
    Provides:
    - Calculate Pareto score for a feature
    - Re-score all features in backlog
    - Get top features by score
    - Learning-based score adjustment (optional)
    """
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        
        # Weights for Pareto formula
        self.impact_weight = 0.6
        self.effort_weight = 0.3
        self.risk_weight = 0.1
    
    def calculate_pareto_score(
        self,
        impact: int,
        effort: int,
        risk: int,
    ) -> float:
        """
        Calculate Pareto score
        
        Args:
            impact: Impact score (1-10)
            effort: Effort score (1-10)
            risk: Risk score (1-10)
        
        Returns:
            Pareto score (can be negative)
        """
        return (
            (impact * self.impact_weight)
            - (effort * self.effort_weight)
            - (risk * self.risk_weight)
        )
    
    def score_feature(
        self,
        feature_id: str,
        impact: Optional[int] = None,
        effort: Optional[int] = None,
        risk: Optional[int] = None,
    ) -> float:
        """
        Score a single feature
        
        Args:
            feature_id: Feature ID
            impact: Override impact score (optional)
            effort: Override effort score (optional)
            risk: Override risk score (optional)
        
        Returns:
            New Pareto score
        """
        with self.db.get_session() as session:
            feature = (
                session.query(FeatureBacklog)
                .filter(FeatureBacklog.id == feature_id)
                .first()
            )
            
            if not feature:
                raise ValueError(f"Feature not found: {feature_id}")
            
            # Use provided scores or existing scores
            impact_score = impact if impact is not None else feature.impact_score
            effort_score = effort if effort is not None else feature.effort_score
            risk_score = risk if risk is not None else feature.risk_score
            
            # Calculate new Pareto score
            pareto_score = self.calculate_pareto_score(
                impact=impact_score,
                effort=effort_score,
                risk=risk_score,
            )
            
            # Update feature
            feature.pareto_score = pareto_score
            feature.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info(
                "feature_scored",
                feature_id=feature_id,
                pareto_score=pareto_score,
                impact=impact_score,
                effort=effort_score,
                risk=risk_score,
            )
            
            return pareto_score
    
    def re_score_all(
        self,
        project_id: str,
        learning_adjustments: Optional[Dict[str, float]] = None,
    ) -> int:
        """
        Re-score all features in backlog
        
        Args:
            project_id: Project ID
            learning_adjustments: Optional adjustments based on learning
                (e.g., {"impact": 0.1} to increase impact weight)
        
        Returns:
            Number of features re-scored
        """
        # Apply learning adjustments if provided
        if learning_adjustments:
            if "impact" in learning_adjustments:
                self.impact_weight += learning_adjustments["impact"]
            if "effort" in learning_adjustments:
                self.effort_weight += learning_adjustments["effort"]
            if "risk" in learning_adjustments:
                self.risk_weight += learning_adjustments["risk"]
        
        with self.db.get_session() as session:
            features = (
                session.query(FeatureBacklog)
                .filter(
                    FeatureBacklog.project_id == project_id,
                    FeatureBacklog.status == "backlog",
                )
                .all()
            )
            
            re_scored_count = 0
            for feature in features:
                # Calculate new Pareto score
                pareto_score = self.calculate_pareto_score(
                    impact=feature.impact_score,
                    effort=feature.effort_score,
                    risk=feature.risk_score,
                )
                
                # Update feature
                feature.pareto_score = pareto_score
                feature.updated_at = datetime.utcnow()
                
                re_scored_count += 1
            
            session.commit()
            
            logger.info(
                "backlog_rescored",
                project_id=project_id,
                features_re_scored=re_scored_count,
            )
            
            return re_scored_count
    
    def get_top_features(
        self,
        project_id: str,
        limit: int = 10,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get top features by Pareto score
        
        Args:
            project_id: Project ID
            limit: Maximum number of features to return
            status: Filter by status (optional)
        
        Returns:
            List of features with scores
        """
        with self.db.get_session() as session:
            query = (
                session.query(FeatureBacklog)
                .filter(FeatureBacklog.project_id == project_id)
            )
            
            if status:
                query = query.filter(FeatureBacklog.status == status)
            
            features = (
                query.order_by(FeatureBacklog.pareto_score.desc())
                .limit(limit)
                .all()
            )
            
            return [
                {
                    "id": f.id,
                    "title": f.title,
                    "pareto_score": f.pareto_score,
                    "impact": f.impact_score,
                    "effort": f.effort_score,
                    "risk": f.risk_score,
                    "category": f.category,
                    "status": f.status,
                }
                for f in features
            ]
    
    def get_daily_priority_feature(
        self,
        project_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the top priority feature for today
        
        Args:
            project_id: Project ID
        
        Returns:
            Top feature or None if backlog is empty
        """
        top_features = self.get_top_features(
            project_id=project_id,
            limit=1,
            status="backlog",
        )
        
        if top_features:
            feature = top_features[0]
            
            logger.info(
                "daily_priority_feature_selected",
                feature_id=feature["id"],
                feature_title=feature["title"],
                pareto_score=feature["pareto_score"],
            )
            
            return feature
        
        return None
    
    def adjust_scores_based_on_learning(
        self,
        completed_features: List[str],
        actual_impact: Dict[str, int],
        actual_effort: Dict[str, int],
    ) -> Dict[str, float]:
        """
        Adjust scoring weights based on learning from completed features
        
        Args:
            completed_features: List of completed feature IDs
            actual_impact: Actual impact scores (feature_id -> score)
            actual_effort: Actual effort scores (feature_id -> effort)
        
        Returns:
            Adjustments to apply to weights
        """
        if not completed_features:
            return {}
        
        # Calculate estimation accuracy
        impact_errors = []
        effort_errors = []
        
        with self.db.get_session() as session:
            for feature_id in completed_features:
                feature = (
                    session.query(FeatureBacklog)
                    .filter(FeatureBacklog.id == feature_id)
                    .first()
                )
                
                if not feature:
                    continue
                
                # Calculate estimation errors
                if feature_id in actual_impact:
                    impact_error = abs(feature.impact_score - actual_impact[feature_id])
                    impact_errors.append(impact_error)
                
                if feature_id in actual_effort:
                    effort_error = abs(feature.effort_score - actual_effort[feature_id])
                    effort_errors.append(effort_error)
        
        # Calculate average errors
        avg_impact_error = sum(impact_errors) / len(impact_errors) if impact_errors else 0
        avg_effort_error = sum(effort_errors) / len(effort_errors) if effort_errors else 0
        
        # Determine adjustments
        adjustments = {}
        
        # If impact estimation is consistently off, reduce its weight
        if avg_impact_error > 2.0:
            adjustments["impact"] = -0.1
        
        # If effort estimation is consistently off, increase its weight
        if avg_effort_error > 2.0:
            adjustments["effort"] = 0.1
        
        logger.info(
            "scoring_weights_adjusted",
            avg_impact_error=avg_impact_error,
            avg_effort_error=avg_effort_error,
            adjustments=adjustments,
        )
        
        return adjustments


# ============================================================================
# Factory Function
# ============================================================================
def get_pareto_scorer(db: DatabaseManager) -> ParetoScorer:
    """Get Pareto scorer instance"""
    return ParetoScorer(db)
