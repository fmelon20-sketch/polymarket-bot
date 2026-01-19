"""Edge domain filter for identifying markets where you have knowledge advantage."""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class EdgeDomain(Enum):
    """Domains where you have a knowledge edge."""
    FOOTBALL_EURO = "football_euro"
    FOOTBALL_INTL = "football_intl"
    LOL_LEC = "lol_lec"
    POLITICS_FR = "politics_fr"
    SOCIETY_FR = "society_fr"
    WEATHER = "weather"
    EARTHQUAKE = "earthquake"


@dataclass
class EdgeMatch:
    """Result of an edge domain match."""
    domain: EdgeDomain
    matched_keywords: list[str]
    confidence: float  # 0.0 to 1.0


# Keywords for each domain (case-insensitive matching)
EDGE_KEYWORDS: dict[EdgeDomain, list[str]] = {
    EdgeDomain.FOOTBALL_EURO: [
        # Leagues
        "ligue 1", "premier league", "la liga", "serie a", "bundesliga",
        "champions league", "europa league", "conference league",
        "eredivisie", "primeira liga", "super lig",
        # French clubs
        "psg", "paris saint-germain", "marseille", "lyon", "monaco", "lille",
        "lens", "nice", "rennes", "nantes", "strasbourg", "toulouse",
        # English clubs
        "manchester united", "manchester city", "liverpool", "chelsea fc", "arsenal",
        "tottenham", "newcastle", "west ham", "aston villa", "brighton",
        # Spanish clubs
        "real madrid", "barcelona", "atletico madrid", "sevilla", "valencia",
        "villarreal", "real sociedad", "athletic bilbao",
        # Italian clubs
        "juventus", "inter milan", "ac milan", "napoli", "roma", "lazio", "atalanta",
        # German clubs
        "bayern munich", "borussia dortmund", "rb leipzig", "bayer leverkusen",
        # Other top clubs
        "ajax", "psv", "benfica", "porto", "sporting",
        # Generic football terms (only with other context)
        "ballon d'or", "golden boot", "ucl", "uel",
    ],

    EdgeDomain.FOOTBALL_INTL: [
        # Competitions
        "world cup", "coupe du monde", "euro 2024", "euro 2028", "euros",
        "nations league", "copa america", "african cup", "afcon",
        "asian cup", "concacaf", "qualifiers",
        # National teams
        "france national", "les bleus", "equipe de france",
        "england national", "germany national", "spain national",
        "italy national", "brazil national", "argentina national",
        # Players (French + top international)
        "mbappe", "mbappé", "griezmann", "dembele", "dembélé", "giroud",
        "kante", "kanté", "pogba", "benzema", "tchouameni", "camavinga",
        "messi", "ronaldo", "haaland", "bellingham", "vinicius",
    ],

    EdgeDomain.LOL_LEC: [
        # League - be very specific to avoid false positives
        "league of legends", "lol esports",
        # Teams - use full names to avoid conflicts
        "fnatic esports", "g2 esports", "mad lions", "team vitality esports",
        "team heretics", "karmine corp", "kcorp",
        # Events - specific
        "lec winter", "lec spring", "lec summer", "lol worlds",
    ],

    EdgeDomain.POLITICS_FR: [
        # Politicians
        "macron", "le pen", "marine le pen", "mélenchon", "melenchon",
        "bardella", "attal", "borne", "darmanin", "le maire",
        "zemmour", "ciotti", "wauquiez", "glucksmann", "roussel",
        "ruffin", "philippe", "edouard philippe", "sarkozy", "hollande",
        # Parties
        "renaissance", "rassemblement national", "rn", "lfi", "france insoumise",
        "les républicains", "lr", "parti socialiste", "ps", "eelv",
        "reconquête", "reconquete", "nupes", "nfp", "nouveau front populaire",
        # Institutions
        "assemblée nationale", "assemblee nationale", "sénat", "senat",
        "elysée", "elysee", "matignon", "conseil constitutionnel",
        # Events
        "french election", "france election", "législatives", "legislatives",
        "présidentielle", "presidentielle", "municipales", "européennes",
    ],

    EdgeDomain.SOCIETY_FR: [
        # Geographic
        "france", "french", "paris", "française", "francaise", "français", "francais",
        "lyon", "marseille", "bordeaux", "toulouse", "nice", "nantes", "strasbourg",
        # Media/Culture
        "tf1", "france 2", "bfm", "cnews", "le monde", "le figaro", "libération",
        # Events/Topics
        "gilets jaunes", "yellow vests france", "grève france", "strike france",
        "retraites france", "pension france",
    ],

    EdgeDomain.WEATHER: [
        # General
        "weather", "météo", "meteo", "temperature", "températures",
        "heat wave", "canicule", "cold wave", "vague de froid",
        "snow", "neige", "rain", "pluie", "storm", "tempête", "tempete",
        "flooding", "inondation", "drought", "sécheresse", "secheresse",
        # Specific to France/Europe
        "france weather", "europe weather", "paris weather",
        "météo france", "meteo france",
    ],

    EdgeDomain.EARTHQUAKE: [
        # Terms
        "earthquake", "tremblement de terre", "séisme", "seisme",
        "magnitude", "richter", "aftershock", "réplique",
        "seismic", "sismique", "epicenter", "épicentre",
        "tsunami", "fault line", "faille",
        # Regions you might know
        "earthquake france", "earthquake europe", "earthquake turkey",
        "earthquake japan", "earthquake california",
    ],
}

# Minimum confidence threshold to consider a match
MIN_CONFIDENCE = 0.3


class EdgeFilter:
    """Filters markets based on edge domains."""

    def __init__(self):
        # Pre-compile regex patterns for efficiency
        self._patterns: dict[EdgeDomain, list[re.Pattern]] = {}
        for domain, keywords in EDGE_KEYWORDS.items():
            self._patterns[domain] = [
                re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
                for kw in keywords
            ]

    def check_market(self, question: str, tags: list[str] = None) -> Optional[EdgeMatch]:
        """
        Check if a market matches any edge domain.

        Args:
            question: The market question text
            tags: Optional list of market tags

        Returns:
            EdgeMatch if the market matches an edge domain, None otherwise
        """
        text = question.lower()
        if tags:
            text += " " + " ".join(tags).lower()

        best_match: Optional[EdgeMatch] = None
        best_confidence = 0.0

        for domain, patterns in self._patterns.items():
            matched_keywords = []

            for pattern, keyword in zip(patterns, EDGE_KEYWORDS[domain]):
                if pattern.search(text):
                    matched_keywords.append(keyword)

            if matched_keywords:
                # Calculate confidence based on number of matches
                # More matches = higher confidence
                confidence = min(1.0, len(matched_keywords) * 0.3)

                # Boost confidence for highly specific matches
                if len(matched_keywords) >= 3:
                    confidence = min(1.0, confidence + 0.2)

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = EdgeMatch(
                        domain=domain,
                        matched_keywords=matched_keywords,
                        confidence=confidence,
                    )

        # Only return if confidence is above threshold
        if best_match and best_match.confidence >= MIN_CONFIDENCE:
            return best_match

        return None

    def matches_edge(self, question: str, tags: list[str] = None) -> bool:
        """Quick check if a market matches any edge domain."""
        return self.check_market(question, tags) is not None

    def get_domain_emoji(self, domain: EdgeDomain) -> str:
        """Get emoji for a domain."""
        emoji_map = {
            EdgeDomain.FOOTBALL_EURO: "⚽",
            EdgeDomain.FOOTBALL_INTL: "🏆",
            EdgeDomain.LOL_LEC: "🎮",
            EdgeDomain.POLITICS_FR: "🇫🇷",
            EdgeDomain.SOCIETY_FR: "🗼",
            EdgeDomain.WEATHER: "🌦️",
            EdgeDomain.EARTHQUAKE: "🌍",
        }
        return emoji_map.get(domain, "📊")

    def get_domain_name(self, domain: EdgeDomain) -> str:
        """Get human-readable name for a domain."""
        name_map = {
            EdgeDomain.FOOTBALL_EURO: "Football Europe",
            EdgeDomain.FOOTBALL_INTL: "Football International",
            EdgeDomain.LOL_LEC: "LoL / LEC",
            EdgeDomain.POLITICS_FR: "Politique FR",
            EdgeDomain.SOCIETY_FR: "France & Société",
            EdgeDomain.WEATHER: "Météo",
            EdgeDomain.EARTHQUAKE: "Séismes",
        }
        return name_map.get(domain, domain.value)


# Global instance
edge_filter = EdgeFilter()
