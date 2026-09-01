from rest_framework import serializers

from apps.trips.models import Trip

from .models import Review


class ReviewReadSerializer(serializers.ModelSerializer):
    """Lecture d'un avis (public et admin)."""

    author = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "company",
            "company_name",
            "trip",
            "author",
            "rating",
            "comment",
            "response",
            "responded_at",
            "is_flagged",
            "is_testimonial",
            "created_at",
        ]

    def get_author(self, review: Review) -> str:
        # Prenom + initiale du nom (on n'expose pas l'identite complete).
        user = review.user
        initial = f"{user.nom[:1]}." if user.nom else ""
        return f"{user.prenom} {initial}".strip()


class ReviewCreateSerializer(serializers.ModelSerializer):
    """Depot d'un avis par un voyageur (validation metier dans le service)."""

    trip = serializers.PrimaryKeyRelatedField(queryset=Trip.objects.all())

    class Meta:
        model = Review
        fields = ["trip", "rating", "comment"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("La note doit etre comprise entre 1 et 5.")
        return value


class ReviewRespondSerializer(serializers.Serializer):
    """Reponse d'un admin de compagnie a un avis."""

    response = serializers.CharField()


class TestimonialSerializer(serializers.ModelSerializer):
    """Temoignage valide, affiche sur la page d'accueil publique."""

    author = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "company",
            "company_name",
            "author",
            "rating",
            "comment",
            "created_at",
        ]

    def get_author(self, review: Review) -> str:
        # Prenom + initiale du nom (on n'expose jamais l'identite complete).
        user = review.user
        initial = f"{user.nom[:1]}." if user.nom else ""
        return f"{user.prenom} {initial}".strip()


class TestimonialToggleSerializer(serializers.Serializer):
    """Mise en avant (ou retrait) d'un avis en temoignage par le super admin."""

    is_testimonial = serializers.BooleanField(default=True)
