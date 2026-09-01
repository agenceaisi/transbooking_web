"""Donnees de reference de la commande `seed_demo`.

Regroupe les constantes (villes, distances, patronymes, libelles metier) pour
garder `seed_demo.py` centre sur la logique de generation. Aucune de ces
donnees n'est ecrite telle quelle : la commande les combine avec la graine
aleatoire fournie par `--seed`.
"""

from decimal import Decimal

# ---------------------------------------------------------------------------
# Geographie
# ---------------------------------------------------------------------------

# Villes reelles du Burkina Faso avec leur region administrative.
CITIES: dict[str, str] = {
    "Ouagadougou": "Centre",
    "Bobo-Dioulasso": "Hauts-Bassins",
    "Koudougou": "Centre-Ouest",
    "Ouahigouya": "Nord",
    "Banfora": "Cascades",
    "Kaya": "Centre-Nord",
    "Tenkodogo": "Centre-Est",
    "Fada N'Gourma": "Est",
    "Dedougou": "Boucle du Mouhoun",
    "Gaoua": "Sud-Ouest",
}

# ---------------------------------------------------------------------------
# Identites burkinabe
# ---------------------------------------------------------------------------

PRENOMS = [
    "Ibrahim", "Aminata", "Boureima", "Fatimata", "Rasmane", "Salimata",
    "Adama", "Mariam", "Issa", "Awa", "Souleymane", "Bintou", "Moussa",
    "Kadiatou", "Yacouba", "Rokia", "Hamidou", "Safiatou", "Karim", "Assetou",
    "Ousmane", "Djeneba", "Seydou", "Habibou", "Idrissa", "Nafissatou",
    "Abdoulaye", "Ramata", "Alassane", "Korotimi",
]

NOMS = [
    "Ouedraogo", "Sawadogo", "Kabore", "Traore", "Sana", "Compaore", "Zongo",
    "Kone", "Bationo", "Nikiema", "Ilboudo", "Ky", "Coulibaly", "Sanou",
    "Diallo", "Barry", "Tapsoba", "Bamogo", "Nacoulma", "Zerbo", "Ouattara",
    "Some", "Dabire", "Kambou",
]

# Marques et modeles courants sur les lignes interurbaines burkinabe.
BRANDS = [
    ("Mercedes-Benz", "Sprinter"),
    ("Toyota", "Coaster"),
    ("Yutong", "ZK6122"),
    ("King Long", "XMQ6127"),
    ("Higer", "KLQ6122"),
    ("Iveco", "Daily"),
]

# ---------------------------------------------------------------------------
# Compagnies
# ---------------------------------------------------------------------------

# Compagnie principale : celle utilisee pour tester tous les ecrans metier.
MAIN_COMPANY = {
    "name": "Rakieta Transport",
    "sigle": "RKT",
    "city": "Ouagadougou",
    "primary_color": "#C0392B",
    "commission_rate": Decimal("8.00"),
    "description": (
        "Compagnie de transport interurbain desservant les principaux axes "
        "du Burkina Faso depuis 1998."
    ),
    "welcome_message": "Bienvenue chez Rakieta Transport, votre confort est notre priorite.",
}

# Deuxieme compagnie active, volontairement plus petite : sert a verifier
# l'isolation multi-tenant (ses donnees ne doivent jamais apparaitre cote RKT).
SECOND_COMPANY = {
    "name": "TSR - Transport Sana Rasmane",
    "sigle": "TSR",
    "city": "Ouagadougou",
    "primary_color": "#2471A3",
    "commission_rate": Decimal("10.00"),
    "description": "Transporteur regional sur l'axe Ouagadougou - Boucle du Mouhoun.",
    "welcome_message": "TSR, la route en toute serenite.",
}

# Compagnie suspendue : alimente l'ecran « compte suspendu » et les 403.
SUSPENDED_COMPANY = {
    "name": "STAF Voyages",
    "sigle": "STAF",
    "city": "Bobo-Dioulasso",
    "primary_color": "#27AE60",
    "commission_rate": None,  # applique le taux global de la plateforme
    "description": "Compagnie suspendue pour abonnement impaye.",
    "welcome_message": "",
    "suspension_reason": (
        "Abonnement expire depuis plus de 30 jours et relances restees sans "
        "reponse. Regularisez votre situation pour reactiver votre compte."
    ),
}

# Demandes d'inscription en instruction (ecran super admin « Demandes
# d'inscription »). Ce sont des lignes Company sans flotte ni admin : le
# modele ne distingue pas la demande de la compagnie, seul `status` change
# (cf. companies.models.OPEN_REQUEST_STATUSES).
COMPANY_REQUESTS = [
    {
        "name": "Sogebaf Transport",
        "sigle": "SGB",
        "city": "Ouagadougou",
        "status": "pending",
        "responsible_name": "Salif Nikiema",
        "description": "Demande d'ouverture de compte transporteur interurbain.",
    },
    {
        "name": "Elitis Transport",
        "sigle": "ELT",
        "city": "Koudougou",
        "status": "pending",
        "responsible_name": "Clarisse Ilboudo",
        "description": "Nouvelle compagnie sur l'axe Koudougou - Ouagadougou.",
    },
    {
        "name": "Rayimi Voyages",
        "sigle": "RYM",
        "city": "Ouahigouya",
        "status": "info_requested",
        "responsible_name": "Hamado Sawadogo",
        "description": "Demande d'agrement pour la desserte du Nord.",
        "info_request_message": (
            "Merci de transmettre le registre de commerce (RCCM) lisible ainsi "
            "que l'attestation d'assurance en cours de validite."
        ),
    },
]

# ---------------------------------------------------------------------------
# Reseau : gares et lignes
# ---------------------------------------------------------------------------

# Gares de la compagnie principale : (ville, nom, adresse).
MAIN_STATIONS = [
    ("Ouagadougou", "Gare Rakieta Ouaga Patte d'Oie", "Avenue Bassawarga, Patte d'Oie"),
    ("Bobo-Dioulasso", "Gare Rakieta Bobo Centre", "Avenue de la Nation, secteur 4"),
    ("Koudougou", "Gare Rakieta Koudougou", "Route de Ouagadougou, secteur 7"),
    ("Banfora", "Gare Rakieta Banfora", "Avenue de la Comoe"),
    ("Ouahigouya", "Gare Rakieta Ouahigouya", "Route de Ouaga, secteur 3"),
]

SECOND_STATIONS = [
    ("Ouagadougou", "Gare TSR Ouaga Ouagainter", "Zone industrielle de Kossodo"),
    ("Dedougou", "Gare TSR Dedougou", "Avenue de l'Independance"),
]

# Lignes de la compagnie principale :
# (origine, destination, distance_km, prix_fcfa, duree_minutes).
# Distances routieres reelles, tarifs plausibles pour de l'interurbain.
MAIN_ROUTES = [
    ("Ouagadougou", "Bobo-Dioulasso", 360, 7000, 300),
    ("Bobo-Dioulasso", "Ouagadougou", 360, 7000, 300),
    ("Ouagadougou", "Koudougou", 100, 2000, 90),
    ("Ouagadougou", "Ouahigouya", 182, 3500, 165),
    ("Ouagadougou", "Fada N'Gourma", 220, 4000, 195),
    ("Ouagadougou", "Kaya", 100, 2000, 90),
    ("Bobo-Dioulasso", "Banfora", 85, 1500, 75),
    ("Ouagadougou", "Tenkodogo", 180, 3000, 150),
]

SECOND_ROUTES = [
    ("Ouagadougou", "Dedougou", 230, 4000, 210),
    ("Dedougou", "Bobo-Dioulasso", 180, 3500, 165),
]

# Escales intermediaires : {(origine, destination): [(ville, prix_partiel)]}
ROUTE_STOPS = {
    ("Ouagadougou", "Bobo-Dioulasso"): [("Koudougou", 2000), ("Boromo", 4000)],
    ("Bobo-Dioulasso", "Ouagadougou"): [("Boromo", 3000), ("Koudougou", 5000)],
    ("Ouagadougou", "Ouahigouya"): [("Yako", 2000)],
}

# Villes d'escale absentes de la liste principale (creees a la demande).
STOP_CITIES = {
    "Boromo": "Boucle du Mouhoun",
    "Yako": "Nord",
}

# ---------------------------------------------------------------------------
# Forfaits d'abonnement
# ---------------------------------------------------------------------------

PLANS = [
    {
        "name": "Essentiel Mensuel",
        "price": Decimal("25000"),
        "duration_months": 1,
        "description": "Forfait d'entree : jusqu'a 5 vehicules et 8 agents.",
        "features": {"max_vehicles": 5, "max_agents": 8, "support": "standard"},
    },
    {
        "name": "Pro Mensuel",
        "price": Decimal("60000"),
        "duration_months": 1,
        "description": "Forfait intermediaire : 15 vehicules, 25 agents, support prioritaire.",
        "features": {"max_vehicles": 15, "max_agents": 25, "support": "prioritaire"},
    },
    {
        "name": "Premium Annuel",
        "price": Decimal("600000"),
        "duration_months": 12,
        "description": "Forfait annuel : flotte illimitee et support dedie.",
        "features": {"max_vehicles": 50, "max_agents": 100, "support": "dedie"},
    },
]

# ---------------------------------------------------------------------------
# Relation client
# ---------------------------------------------------------------------------

# Commentaires d'avis indexes par note, pour rester coherents avec l'etoile.
REVIEW_COMMENTS = {
    5: [
        "Voyage impeccable, depart a l'heure et chauffeur tres prudent.",
        "Bus propre et climatise, personnel accueillant. Je recommande.",
        "Excellent service au guichet, billet obtenu en deux minutes.",
        "Rien a redire, arrivee en avance sur l'horaire annonce.",
    ],
    4: [
        "Bon voyage dans l'ensemble, juste un peu d'attente au depart.",
        "Confort correct et prix raisonnable pour la distance.",
        "Chauffeur professionnel, la climatisation pourrait etre plus forte.",
        "Bonne experience, je reprendrai cette compagnie.",
    ],
    3: [
        "Voyage moyen : une heure de retard mais trajet sans incident.",
        "Bus correct mais les sieges du fond sont fatigues.",
        "Service acceptable, l'attente en gare est trop longue.",
    ],
    2: [
        "Deux heures de retard sans aucune information des agents.",
        "Climatisation en panne pendant tout le trajet, tres inconfortable.",
        "Bagages mal ranges, j'ai du reclamer a l'arrivee.",
    ],
    1: [
        "Voyage annule au dernier moment, aucun remboursement propose.",
        "Personnel desagreable et bus surcharge. Experience a oublier.",
        "Trois heures de retard, je ne recommande pas du tout.",
    ],
}

# Reponses type de la compagnie aux avis.
REVIEW_RESPONSES = [
    "Merci pour votre retour, nous transmettons vos remarques a nos equipes.",
    "Nous vous prions d'accepter nos excuses et travaillons a ameliorer ce point.",
    "Merci de votre fidelite, au plaisir de vous transporter a nouveau.",
]

# Reclamations : {type: (sujet, description)}
CLAIM_TEMPLATES = {
    "retard": (
        "Retard important au depart",
        "Le bus prevu a 07h00 n'est parti qu'a 10h30 sans aucune explication "
        "des agents en gare. J'ai manque mon rendez-vous a l'arrivee.",
    ),
    "perte_bagage": (
        "Bagage non retrouve a l'arrivee",
        "Mon sac de voyage enregistre au depart de Ouagadougou n'etait pas "
        "dans la soute a l'arrivee. Il contenait des effets personnels.",
    ),
    "bagage_endommage": (
        "Valise endommagee pendant le transport",
        "Ma valise est arrivee avec une roue cassee et la fermeture eclair "
        "arrachee. Je demande une prise en charge de la reparation.",
    ),
    "comportement": (
        "Comportement du personnel de bord",
        "Le receveur s'est montre irrespectueux envers plusieurs passagers "
        "lors du controle des billets.",
    ),
    "surcharge": (
        "Surcharge du vehicule",
        "Des passagers etaient debout dans l'allee sur tout le trajet alors "
        "que le bus etait deja complet. C'est dangereux.",
    ),
    "remboursement": (
        "Demande de remboursement apres annulation",
        "Mon voyage a ete annule par la compagnie et je n'ai toujours pas ete "
        "rembourse malgre deux passages en gare.",
    ),
    "autre": (
        "Climatisation hors service",
        "La climatisation n'a pas fonctionne pendant les cinq heures de trajet "
        "malgre les signalements faits au chauffeur.",
    ),
}

# Reponses apportees par la compagnie aux reclamations traitees.
CLAIM_RESPONSES = [
    "Nous avons identifie l'incident et pris des mesures aupres de l'equipe concernee.",
    "Votre dossier a ete valide, le remboursement sera effectue sous 72 heures.",
    "Apres verification, votre bagage a ete retrouve et vous attend en gare.",
]

# Signalements d'exces de vitesse : (description, vitesse estimee km/h).
SPEED_REPORT_TEMPLATES = [
    ("Le chauffeur a double sur la ligne continue a vive allure vers Boromo.", 125),
    ("Vitesse excessive sur la portion en travaux, passagers inquiets.", 110),
    ("Le bus roulait bien au-dela de la limite autorisee malgre la pluie.", 118),
    ("Depassement dangereux d'un camion en cote apres Koudougou.", 130),
]

# Coordonnees GPS approximatives des villes, pour les signalements geolocalises.
CITY_COORDS = {
    "Ouagadougou": (Decimal("12.371400"), Decimal("-1.519700")),
    "Bobo-Dioulasso": (Decimal("11.177100"), Decimal("-4.297900")),
    "Koudougou": (Decimal("12.252600"), Decimal("-2.362300")),
    "Ouahigouya": (Decimal("13.583200"), Decimal("-2.421900")),
    "Banfora": (Decimal("10.633400"), Decimal("-4.762400")),
    "Kaya": (Decimal("13.091800"), Decimal("-1.084200")),
    "Tenkodogo": (Decimal("11.780100"), Decimal("-0.369700")),
    "Fada N'Gourma": (Decimal("12.061800"), Decimal("0.358400")),
    "Dedougou": (Decimal("12.463800"), Decimal("-3.460900")),
    "Gaoua": (Decimal("10.325800"), Decimal("-3.184100")),
}

# ---------------------------------------------------------------------------
# Colis
# ---------------------------------------------------------------------------

PARCEL_NATURES = [
    "Vetements", "Documents administratifs", "Pieces detachees auto",
    "Produits vivriers", "Materiel informatique", "Medicaments",
    "Ustensiles de cuisine", "Echantillons textiles",
]

# Natures necessitant la mention FRAGILE sur le bordereau.
FRAGILE_NATURES = {"Materiel informatique", "Medicaments", "Ustensiles de cuisine"}

# ---------------------------------------------------------------------------
# Comptes de demonstration
# ---------------------------------------------------------------------------

# Bloc de numeros reserve aux comptes de demonstration. `--reset` purge tous
# les comptes non-superutilisateur de ce bloc, y compris ceux laisses par une
# version anterieure du seed. N'attribuez jamais un numero de ce bloc a un
# compte reel.
DEMO_PHONE_PREFIX = "+22670000"

# Roster fige : chaque compte a un numero stable dans le bloc +226700000xx.
# Cette stabilite sert a deux choses : l'idempotence (get_or_create sur le
# telephone, qui est le USERNAME_FIELD) et la purge ciblee de `--reset`, qui
# ne touche qu'a ces comptes.
#   company : "main" | "second" | None (super admin, voyageurs)
#   station : index dans MAIN_STATIONS / SECOND_STATIONS, ou None
DEMO_USERS = [
    {
        "key": "super_admin",
        "phone": "+22670000001",
        "prenom": "Awa",
        "nom": "Konseiga",
        "email": "awa.konseiga@transbooking.bf",
        "role": "super_admin",
        "company": None,
        "station": None,
        "label": "Super administrateur plateforme",
    },
    {
        "key": "main_admin",
        "phone": "+22670000010",
        "prenom": "Boukary",
        "nom": "Ouedraogo",
        "email": "admin@rakieta.bf",
        "role": "company_admin",
        "company": "main",
        "station": None,
        "label": "Admin compagnie principale",
    },
    {
        "key": "main_agent_ouaga",
        "phone": "+22670000011",
        "prenom": "Salimata",
        "nom": "Kabore",
        "email": "s.kabore@rakieta.bf",
        "role": "agent_guichet",
        "company": "main",
        "station": 0,
        "label": "Agent guichet - Gare Ouaga Patte d'Oie",
    },
    {
        "key": "main_agent_bobo",
        "phone": "+22670000012",
        "prenom": "Rasmane",
        "nom": "Sawadogo",
        "email": "r.sawadogo@rakieta.bf",
        "role": "agent_guichet",
        "company": "main",
        "station": 1,
        "label": "Agent guichet - Gare Bobo Centre",
    },
    {
        "key": "main_controleur",
        "phone": "+22670000013",
        "prenom": "Issa",
        "nom": "Traore",
        "email": "i.traore@rakieta.bf",
        "role": "controleur",
        "company": "main",
        "station": 0,
        "label": "Controleur a bord",
    },
    {
        "key": "second_admin",
        "phone": "+22670000020",
        "prenom": "Mariam",
        "nom": "Sana",
        "email": "admin@tsr.bf",
        "role": "company_admin",
        "company": "second",
        "station": None,
        "label": "Admin 2e compagnie (isolation multi-tenant)",
    },
    {
        "key": "second_agent",
        "phone": "+22670000021",
        "prenom": "Adama",
        "nom": "Zongo",
        "email": "a.zongo@tsr.bf",
        "role": "agent_guichet",
        "company": "second",
        "station": 0,
        "label": "Agent guichet 2e compagnie",
    },
    {
        "key": "voyageur_riche",
        "phone": "+22670000030",
        "prenom": "Ibrahim",
        "nom": "Compaore",
        "email": "ibrahim.compaore@mail.bf",
        "role": "voyageur",
        "company": None,
        "station": None,
        "label": "Voyageur avec historique complet (a utiliser pour l'espace voyageur)",
    },
    {
        "key": "voyageur_2",
        "phone": "+22670000031",
        "prenom": "Fatimata",
        "nom": "Nikiema",
        "email": "fatimata.nikiema@mail.bf",
        "role": "voyageur",
        "company": None,
        "station": None,
        "label": "Voyageur",
    },
    {
        "key": "voyageur_3",
        "phone": "+22670000032",
        "prenom": "Souleymane",
        "nom": "Ilboudo",
        "email": "souleymane.ilboudo@mail.bf",
        "role": "voyageur",
        "company": None,
        "station": None,
        "label": "Voyageur",
    },
    {
        "key": "voyageur_4",
        "phone": "+22670000033",
        "prenom": "Bintou",
        "nom": "Diallo",
        "email": "bintou.diallo@mail.bf",
        "role": "voyageur",
        "company": None,
        "station": None,
        "label": "Voyageur",
    },
    {
        "key": "voyageur_5",
        "phone": "+22670000034",
        "prenom": "Yacouba",
        "nom": "Tapsoba",
        "email": "yacouba.tapsoba@mail.bf",
        "role": "voyageur",
        "company": None,
        "station": None,
        "label": "Voyageur",
    },
]

# Cles des comptes voyageurs, dans l'ordre du roster.
VOYAGEUR_KEYS = [u["key"] for u in DEMO_USERS if u["role"] == "voyageur"]

# ---------------------------------------------------------------------------
# Divers
# ---------------------------------------------------------------------------

DRIVER_NAMES = [
    "Salif Ouedraogo", "Mahamadi Kabore", "Drissa Sanou", "Zakaria Compaore",
    "Noufou Sawadogo", "Ali Traore", "Boukary Zongo", "Lassane Nikiema",
]

# Motifs d'annulation de voyage cote compagnie.
TRIP_CANCELLATION_REASONS = [
    "Panne mecanique du vehicule, aucun bus de remplacement disponible.",
    "Nombre de reservations insuffisant pour assurer le depart.",
    "Route coupee par les intemperies sur l'axe prevu.",
]
