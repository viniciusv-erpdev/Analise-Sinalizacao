import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.conf import settings

from signaling.characterization import MAX_TECHNICAL_ANALYSIS_LENGTH, validate_report_text
from signaling.intersection_problems import problem_solution_codes, validate_problem_solution


DEFAULT_SIGNALING_SEARCH_RADIUS_METERS = 50
MIN_SIGNALING_SEARCH_RADIUS_METERS = 10
MAX_SIGNALING_SEARCH_RADIUS_METERS = 300


class SignalingPoint(models.Model):
    class Status(models.TextChoices):
        OK = "OK", "Adequada"
        INCOMPLETE = "INCOMPLETE", "Incompleta"
        ABSENT = "ABSENT", "Ausente"

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    search_radius_meters = models.PositiveSmallIntegerField(
        default=DEFAULT_SIGNALING_SEARCH_RADIUS_METERS,
        validators=[
            MinValueValidator(MIN_SIGNALING_SEARCH_RADIUS_METERS),
            MaxValueValidator(MAX_SIGNALING_SEARCH_RADIUS_METERS),
        ],
    )
    # Survives removal of a reservation row; never reset while this point exists.
    reservation_generation = models.PositiveBigIntegerField(default=0, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [("generate_signaling_report", "Pode gerar relatórios de sinalização")]

    def __str__(self) -> str:
        return f"Ponto {self.pk} ({self.latitude}, {self.longitude})"


class SignalingIntervention(models.Model):
    class Type(models.TextChoices):
        TRAFFIC_LIGHT = "TRAFFIC_LIGHT", "Semáforo"
        PEDESTRIAN_CROSSING = "PEDESTRIAN_CROSSING", "Travessia segura"
        MINI_ROUNDABOUT = "MINI_ROUNDABOUT", "Minirrotatória"
        RIGHT_OF_WAY_REVERSAL = (
            "RIGHT_OF_WAY_REVERSAL",
            "Inversão de Pref. Passagem",
        )
        TRAFFIC_FLOW_CHANGE = "TRAFFIC_FLOW_CHANGE", "Alteração de circulação"
        PEDESTRIAN_REFUGE = "PEDESTRIAN_REFUGE", "Refúgios para pedestres"
        NO_PARKING = "NO_PARKING", "Proibido estacionar"
        GEOMETRY_ADJUSTMENT = "GEOMETRY_ADJUSTMENT", "Adequação na geometria"
        SPEED_REDUCTION = "SPEED_REDUCTION", "Redução de velocidade"
        VERTICAL_HORIZONTAL_SIGNALING = (
            "VERTICAL_HORIZONTAL_SIGNALING",
            "Sinalizações verticais e horizontais",
        )
        LOW_VISIBILITY = "LOW_VISIBILITY", "Visibilidade prejudicada"
        R1 = "R1", "R-1"
        STREET_LIGHTING = "STREET_LIGHTING", "Iluminação"
        SPEED_BUMP = "SPEED_BUMP", "Lombada"
        R5A = "R5A", "R-5a"
        R5B = "R5B", "R-5b"
        R4A = "R4A", "R-4a"
        R24A = "R24A", "R-24a"
        R6C = "R6C", "R-6c"
        R6A = "R6A", "R-6a"
        RAISED_CROSSWALK = "RAISED_CROSSWALK", "Faixa elevada"

    class Condition(models.TextChoices):
        OK = "OK", "Presente"
        ABSENT = "ABSENT", "Ausente"

    signaling_point = models.ForeignKey(
        SignalingPoint,
        on_delete=models.CASCADE,
        related_name="interventions",
    )
    type = models.CharField(max_length=30, choices=Type.choices)
    condition = models.CharField(max_length=6, choices=Condition.choices)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_type_display()} - {self.get_condition_display()}"


class SignalingPointProblem(models.Model):
    signaling_point = models.ForeignKey(
        SignalingPoint, on_delete=models.CASCADE, related_name="problems",
    )
    problem_code = models.CharField(
        max_length=2,
        choices=[(code, code) for code, _ in problem_solution_codes()],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["problem_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["signaling_point", "problem_code"],
                name="unique_problem_per_signaling_point",
            ),
            models.CheckConstraint(
                condition=models.Q(problem_code__in=[code for code, _ in problem_solution_codes()]),
                name="valid_signaling_problem_code",
            ),
        ]

    def __str__(self) -> str:
        return f"Ponto {self.signaling_point_id}: {self.problem_code}"


class SignalingPointProblemSolution(models.Model):
    problem = models.ForeignKey(
        SignalingPointProblem, on_delete=models.CASCADE, related_name="solutions",
    )
    solution_code = models.CharField(
        max_length=3,
        choices=[
            (solution, solution)
            for _, solutions in problem_solution_codes()
            for solution in solutions
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["solution_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "solution_code"], name="unique_solution_per_point_problem",
            ),
            models.CheckConstraint(
                condition=models.Q(solution_code__in=[
                    solution for _, solutions in problem_solution_codes() for solution in solutions
                ]),
                name="valid_point_problem_solution_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.problem_id:
            validate_problem_solution(self.problem.problem_code, self.solution_code)

    def __str__(self) -> str:
        return f"{self.problem_id}: {self.solution_code}"


class WaypointReservation(models.Model):
    """Current acquisition or released tombstone. Never expose credential fields."""
    signaling_point = models.OneToOneField(
        SignalingPoint, on_delete=models.CASCADE, related_name="reservation",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
    )
    session_digest = models.CharField(max_length=64, editable=False)
    interaction_id = models.UUIDField(editable=False)
    token_digest = models.CharField(max_length=64, editable=False)
    generation = models.PositiveBigIntegerField(editable=False)
    acquired_at = models.DateTimeField(editable=False)
    renewed_at = models.DateTimeField(editable=False)
    expires_at = models.DateTimeField(editable=False, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=models.Q(generation__gt=0), name="reservation_generation_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(renewed_at__gte=models.F("acquired_at"))
                & models.Q(expires_at__gt=models.F("renewed_at")),
                name="reservation_valid_times",
            ),
            models.CheckConstraint(
                condition=models.Q(released_at__isnull=True)
                | models.Q(released_at__gte=models.F("acquired_at")),
                name="reservation_release_after_acquire",
            ),
        ]

    def __str__(self):
        return f"Reservation for waypoint {self.signaling_point_id}"


class WaypointReportDraft(models.Model):
    """Shared editable text only. Writes must use the reservation-aware service."""
    signaling_point = models.OneToOneField(
        SignalingPoint, on_delete=models.CASCADE, related_name="report_draft",
    )
    functional_classification = models.CharField(max_length=500, blank=True, default="")
    geometric_configuration = models.CharField(max_length=500, blank=True, default="")
    regulated_speed = models.CharField(max_length=100, blank=True, default="")
    inspection_address = models.CharField(max_length=300, blank=True, default="")
    occurrence_date = models.DateField(null=True, blank=True)
    inspection_date = models.DateField(null=True, blank=True)
    study_reason = models.TextField(
        max_length=2000, blank=True, default="", validators=[MaxLengthValidator(2000)],
    )
    study_objective = models.TextField(
        max_length=2000, blank=True, default="", validators=[MaxLengthValidator(2000)],
    )
    inspector_name = models.CharField(max_length=200, blank=True, default="")
    technical_analysis = models.TextField(
        max_length=MAX_TECHNICAL_ANALYSIS_LENGTH, blank=True, default="",
        validators=[MaxLengthValidator(MAX_TECHNICAL_ANALYSIS_LENGTH), validate_report_text],
    )
    pgts = models.JSONField(default=list, blank=True)
    revision = models.PositiveBigIntegerField(default=1, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()  # Access follows the existing waypoint/report policy.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revision__gt=0), name="report_draft_revision_positive",
            ),
        ]

    def __str__(self):
        return f"Report draft for waypoint {self.signaling_point_id}"


# Official reports are independent of the mutable waypoint/draft lifecycle.


class TechnicalReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    waypoint = models.ForeignKey(SignalingPoint, null=True, blank=True, on_delete=models.SET_NULL)
    waypoint_history = models.JSONField()
    year = models.PositiveSmallIntegerField()
    sequence = models.PositiveIntegerField()
    number_reserved_at = models.DateTimeField()
    number_assigned_at = models.DateTimeField(null=True, blank=True)

    @property
    def official_number(self):
        return f"RTSV-{self.year:04d}-{self.sequence:04d}"

    class Meta:
        default_permissions = ()
        permissions = [
            ("finalize_technicalreport", "Pode finalizar relat\u00f3rios t\u00e9cnicos"),
            ("view_official_reports", "Pode consultar relat\u00f3rios oficiais publicados"),
            ("download_official_reports", "Pode baixar arquivos de relat\u00f3rios oficiais"),
            ("delete_official_reports", "Pode excluir definitivamente relatórios oficiais"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["year", "sequence"], name="report_annual_number_unique"),
            models.CheckConstraint(condition=models.Q(sequence__gte=1, sequence__lte=9999), name="report_sequence_range"),
        ]


IMMUTABLE_VERSION_FIELDS = (
    "report_id", "version", "schema_version", "snapshot", "snapshot_sha256",
    "source_sha256", "author_identity", "issued_at",
)


class ReportVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if set(kwargs) & set(IMMUTABLE_VERSION_FIELDS + ("report",)):
            raise ValidationError("Create a new version instead of changing historical inputs")
        return super().update(**kwargs)


class TechnicalReportVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(TechnicalReport, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField(default=1)
    schema_version = models.PositiveSmallIntegerField(default=1)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    source_sha256 = models.CharField(max_length=64)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    author_identity = models.JSONField()
    issued_at = models.DateTimeField()
    finalized_at = models.DateTimeField(null=True, blank=True)

    objects = ReportVersionQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.values(*IMMUTABLE_VERSION_FIELDS, "finalized_at").get(pk=self.pk)
            if any(previous[name] != getattr(self, name) for name in IMMUTABLE_VERSION_FIELDS):
                raise ValidationError("Historical report inputs are immutable; create another version")
            if previous["finalized_at"] and previous["finalized_at"] != self.finalized_at:
                raise ValidationError("Finalization timestamp is immutable")
        return super().save(*args, **kwargs)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["report", "version"], name="report_version_unique")]


class ReportFinalizationAttempt(models.Model):
    class State(models.TextChoices):
        ADMITTED = "ADMITTED"
        PROCESSING = "PROCESSING"
        STORING = "STORING"
        FINALIZED = "FINALIZED"
        FAILED = "FAILED"
        INTERRUPTED = "INTERRUPTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.OneToOneField(TechnicalReportVersion, on_delete=models.PROTECT, related_name="attempt")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    idempotency_key = models.UUIDField(unique=True)
    request_sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PROCESSING)
    execution_id = models.UUIDField(default=uuid.uuid4)
    deadline = models.DateTimeField(db_index=True, null=True)
    admitted_at = models.DateTimeField(null=True, editable=False)
    execution_contract = models.JSONField(default=dict, editable=False)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(
            condition=(~models.Q(state="ADMITTED")
                       | models.Q(admitted_at__isnull=False, deadline__isnull=True)),
            name="report_admitted_complete",
        )]


class ReportPublicationSlot(models.Model):
    """Durable ownership, never a lease. Only the future executor may release it."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    attempt = models.OneToOneField(
        ReportFinalizationAttempt, null=True, on_delete=models.PROTECT,
        related_name="publication_slot",
    )
    execution_id = models.UUIDField(null=True, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="report_slot_singleton"),
            models.CheckConstraint(
                condition=(models.Q(attempt__isnull=True, execution_id__isnull=True)
                           | models.Q(attempt__isnull=False, execution_id__isnull=False)),
                name="report_slot_owner_pair",
            ),
        ]


class ReportIdentityQuerySet(models.QuerySet):
    def update(self, **kwargs):
        # SET_NULL must remain available to the existing physical deletion policy.
        if kwargs != {"attempt": None}:
            raise ValidationError("Operational identities cannot be rewritten")
        return super().update(**kwargs)


class ReportExecutionIdentity(models.Model):
    """Never-reused launch intent and bound runtime identity; NOT termination proof."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(ReportFinalizationAttempt, null=True, on_delete=models.SET_NULL,
                               related_name="execution_identities")
    attempt_reference = models.UUIDField(editable=False)
    expected_execution_id = models.UUIDField(editable=False)
    execution_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    host_id = models.CharField(max_length=32, editable=False)
    boot_id = models.UUIDField(editable=False)
    unit_name = models.CharField(max_length=100, unique=True, editable=False)
    release_id = models.CharField(max_length=64, editable=False)
    release_root = models.CharField(max_length=1024, editable=False)
    service_user = models.CharField(max_length=64, editable=False)
    prepared_at = models.DateTimeField(auto_now_add=True)
    bound_at = models.DateTimeField(null=True, editable=False)
    invocation_id = models.UUIDField(null=True, editable=False)
    cgroup_path = models.CharField(max_length=512, null=True, editable=False)
    cgroup_inode = models.PositiveBigIntegerField(null=True, editable=False)
    main_pid = models.PositiveIntegerField(null=True, editable=False)
    process_start_ticks = models.PositiveBigIntegerField(null=True, editable=False)

    objects = ReportIdentityQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            frozen = ("attempt_reference", "expected_execution_id", "execution_id", "host_id", "boot_id",
                      "unit_name", "release_id", "release_root", "service_user", "prepared_at")
            bound = ("bound_at", "invocation_id", "cgroup_path", "cgroup_inode", "main_pid", "process_start_ticks")
            previous = type(self).objects.values(*frozen, *bound, "attempt_id").get(pk=self.pk)
            if (any(previous[name] != getattr(self, name) for name in frozen)
                    or (self.attempt_id is not None and previous["attempt_id"] != self.attempt_id)
                    or (previous["bound_at"] and any(previous[name] != getattr(self, name) for name in bound))):
                raise ValidationError("Operational identities are immutable after binding")
        return super().save(*args, **kwargs)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["attempt_reference", "expected_execution_id"], name="report_identity_intention_unique"),
            models.UniqueConstraint(fields=["host_id", "boot_id", "invocation_id"], name="report_identity_invocation_unique"),
            models.CheckConstraint(condition=(
                models.Q(bound_at__isnull=True, invocation_id__isnull=True, cgroup_path__isnull=True,
                         cgroup_inode__isnull=True, main_pid__isnull=True, process_start_ticks__isnull=True)
                | models.Q(bound_at__isnull=False, invocation_id__isnull=False, cgroup_path__isnull=False,
                           cgroup_inode__gt=0, main_pid__gt=0, process_start_ticks__gt=0,
                           cgroup_inode__isnull=False, main_pid__isnull=False, process_start_ticks__isnull=False)
            ), name="report_identity_binding_complete"),
        ]


class ReportOperationalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Operational records are immutable")

    def delete(self):
        raise ValidationError("Operational records are retained")


class ReportOperationalRecord(models.Model):
    """Append-only through the ORM; privileged SQL remains a trust boundary."""
    class Meta:
        abstract = True

    objects = ReportOperationalQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Operational records are immutable")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Operational records are retained")


class ReportReleaseAuthorization(ReportOperationalRecord):
    release_id = models.CharField(max_length=64, primary_key=True)
    bundle_sha256 = models.CharField(max_length=64)
    manifest_sha256 = models.CharField(max_length=64)
    execution_contract = models.JSONField()
    approved_by = models.UUIDField()
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class ReportLaunch(models.Model):
    class State(models.TextChoices):
        REQUESTED = "REQUESTED"
        UNCERTAIN = "UNCERTAIN"
        CONFIRMED = "CONFIRMED"
        TERMINAL_OBSERVED = "TERMINAL_OBSERVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.OneToOneField(ReportExecutionIdentity, on_delete=models.PROTECT, related_name="launch")
    release = models.ForeignKey(ReportReleaseAuthorization, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, choices=State.choices, default=State.REQUESTED)
    contract_sha256 = models.CharField(max_length=64)
    requested_at = models.DateTimeField(auto_now_add=True)
    dispatch_id = models.UUIDField(null=True, unique=True)
    dispatch_started_at = models.DateTimeField(null=True)
    job_id = models.PositiveBigIntegerField(null=True)
    invocation_id = models.UUIDField(null=True)
    confirmed_at = models.DateTimeField(null=True)
    terminal_observed_at = models.DateTimeField(null=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=(
            models.Q(state="REQUESTED", dispatch_id__isnull=True, dispatch_started_at__isnull=True,
                     confirmed_at__isnull=True, job_id__isnull=True, invocation_id__isnull=True,
                     terminal_observed_at__isnull=True)
            | (models.Q(state__in=["UNCERTAIN", "CONFIRMED", "TERMINAL_OBSERVED"],
                        dispatch_id__isnull=False, dispatch_started_at__isnull=False)
               & (models.Q(state="UNCERTAIN", confirmed_at__isnull=True, terminal_observed_at__isnull=True)
                  | models.Q(state="CONFIRMED", confirmed_at__isnull=False, invocation_id__isnull=False,
                             terminal_observed_at__isnull=True)
                  | models.Q(state="TERMINAL_OBSERVED", terminal_observed_at__isnull=False,
                             invocation_id__isnull=False)))
        ), name="report_launch_state_complete")]


class ReportDispatchDelivery(ReportOperationalRecord):
    """One durable handoff. Absence of a receipt NEVER permits another send."""
    id = models.UUIDField(primary_key=True, editable=False)
    launch = models.OneToOneField(ReportLaunch, on_delete=models.PROTECT, related_name="delivery")
    barrier_generation = models.UUIDField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class ReportLauncherReceipt(ReportOperationalRecord):
    """Consumption by the external authority, never a reusable start ticket."""
    id = models.UUIDField(primary_key=True, editable=False)
    launch = models.OneToOneField(ReportLaunch, on_delete=models.PROTECT, related_name="launcher_receipt")
    dispatch_id = models.UUIDField(unique=True, editable=False)
    barrier_generation = models.UUIDField(editable=False)
    peer_uid = models.PositiveIntegerField(editable=False)
    host_id = models.CharField(max_length=32, editable=False)
    boot_id = models.UUIDField(editable=False)
    policy_sha256 = models.CharField(max_length=64, editable=False)
    manifest_sha256 = models.CharField(max_length=64, editable=False)
    bundle_sha256 = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class ReportDeploymentBarrier(models.Model):
    class State(models.TextChoices):
        OPEN = "OPEN"
        DRAINING = "DRAINING"
        DEPLOYING = "DEPLOYING"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    generation = models.UUIDField(default=uuid.uuid4)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="report_deploy_singleton"),
            models.CheckConstraint(condition=models.Q(state__in=["OPEN", "DRAINING", "DEPLOYING"]),
                                   name="report_deploy_state_valid")]


class ReportOperationalEvent(ReportOperationalRecord):
    id = models.UUIDField(primary_key=True, editable=False)
    subject = models.UUIDField()
    kind = models.CharField(max_length=40)
    actor = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class ReportArtifact(models.Model):
    class Kind(models.TextChoices):
        PDF = "PDF"
        DOCX = "DOCX"
        PHOTO = "PHOTO"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(TechnicalReportVersion, on_delete=models.PROTECT, related_name="artifacts")
    kind = models.CharField(max_length=5, choices=Kind.choices)
    ordinal = models.PositiveSmallIntegerField(default=0)
    storage_key = models.CharField(max_length=300, unique=True)
    download_name = models.CharField(max_length=160)
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["version", "kind", "ordinal"], name="report_artifact_kind_ordinal_unique")]


class ReportAnnualCounter(models.Model):
    year = models.PositiveSmallIntegerField(primary_key=True)
    last_reserved = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(last_reserved__lte=9999), name="report_counter_range")]


class ReportDeletion(models.Model):
    """Minimal durable audit and cleanup outbox; deliberately has no report FK."""
    class State(models.TextChoices):
        PENDING = "PENDING"
        FAILED = "FAILED"
        COMPLETE = "COMPLETE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_id = models.UUIDField(unique=True)
    official_number = models.CharField(max_length=20, unique=True)
    deleted_at = models.DateTimeField()
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    deleted_by_username = models.CharField(max_length=150)
    cleanup_state = models.CharField(max_length=8, choices=State.choices, default=State.PENDING)
    pending_keys = models.JSONField(default=list)
    version_ids = models.JSONField(default=list)
    error_code = models.CharField(max_length=40, blank=True)
    cleanup_finished_at = models.DateTimeField(null=True)

    class Meta:
        default_permissions = ()


class DeletedReportKey(models.Model):
    """A one-way idempotency tombstone prevents resurrection of deleted reports."""
    key_sha256 = models.CharField(max_length=64, primary_key=True)
    deletion = models.ForeignKey(ReportDeletion, on_delete=models.PROTECT, related_name="retired_keys")

    class Meta:
        default_permissions = ()
