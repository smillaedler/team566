import datetime
import random

from django.db import models

from django.contrib.auth.models import User


class Player(models.Model):
    
    user = models.ForeignKey(User, related_name="players")
    name = models.CharField(max_length=20, unique=True)
    
    # @@@ points
    
    def __unicode__(self):
        return self.name


class Continent(models.Model):
    
    name = models.CharField(max_length=20)
    
    def __unicode__(self):
        return self.name


class Settlement(models.Model):
    
    name = models.CharField(max_length=20)
    kind = models.CharField(
        max_length=15,
        choices=[
            ("homestead", "Homestead"),
            ("hamlet", "Hamlet"),
            ("village", "Village"),
            ("town", "Town"),
        ],
        default="homestead",
    )
    player = models.ForeignKey(Player, related_name="settlements")
    continent = models.ForeignKey(Continent)
    # location on continent
    x = models.IntegerField()
    y = models.IntegerField()
    
    # @@@ points
    
    def __unicode__(self):
        return u"%s (%s)" % (self.name, self.player)
    
    def place(self, commit=True):
        # @@@ need to test if continent is full otherwise an infinite loop
        # will occur
        y = None
        while y is None:
            x = random.randint(1, 10)
            S = set(range(1, 11)) - set([s.y for s in Settlement.objects.filter(x=x)])
            if S:
                y = random.choice(list(S))
        self.x = x
        self.y = y
        if commit:
            self.save()
    
    def build_queue(self):
        queue = SettlementBuilding.objects.filter(
            settlement=self,
            construction_end__gt=datetime.datetime.now()
        )
        queue = queue.order_by("construction_start")
        return queue
    
    def buildings(self):
        return SettlementBuilding.objects.filter(
            settlement=self,
            construction_end__lte=datetime.datetime.now()
        )


class ResourceKind(models.Model):
    
    name = models.CharField(max_length=25)
    
    def __unicode__(self):
        return self.name


class BaseResourceCount(models.Model):
    
    count = models.IntegerField(default=0)
    timestamp = models.DateTimeField(default=datetime.datetime.now)
    natural_rate = models.DecimalField(max_digits=7, decimal_places=1)
    rate_adjustment = models.DecimalField(max_digits=7, decimal_places=1)
    limit = models.IntegerField(default=0)
    
    class Meta:
        abstract = True
    
    @classmethod
    def current(cls, kind, **kwargs):
        lookup_params = {
            "kind": kind,
            "timestamp__lt": datetime.datetime.now(),
        }
        lookup_params.update(kwargs)
        past = cls._default_manager.filter(**lookup_params).order_by("-timestamp")
        return past[0]
    
    @property
    def rate(self):
        return self.natural_rate + self.rate_adjustment
    
    def amount(self, when=None):
        if when is None:
            when = datetime.datetime.now()
        change = when - self.timestamp
        amt = int(self.count + float(self.rate) * (change.days * 86400 + change.seconds) / 3600.0)
        if self.limit == 0:
            return max(0, amt)
        else:
            return min(max(0, amt), self.limit)


class PlayerResourceCount(BaseResourceCount):
    
    kind = models.ForeignKey(ResourceKind)
    player = models.ForeignKey(Player, related_name="resource_counts")
    
    def __unicode__(self):
        return u"%s (%s)" % (self.kind, self.player)


class SettlementResourceCount(BaseResourceCount):
    
    kind = models.ForeignKey(ResourceKind)
    settlement = models.ForeignKey(Settlement, related_name="resource_counts")
    
    def __unicode__(self):
        return u"%s (%s)" % (self.kind, self.settlement)


class BuildingKind(models.Model):
    
    name = models.CharField(max_length=30)
    
    def __unicode__(self):
        return self.name


class BuildingKindProduct(models.Model):
    
    building_kind = models.ForeignKey(BuildingKind, related_name="products")
    resource_kind = models.ForeignKey(ResourceKind)
    source_terrain_kind = models.ForeignKey("SettlementTerrainKind", null=True)
    base_rate = models.IntegerField()
    
    def __unicode__(self):
        bits = []
        bits.append("%s produces %s" % (self.building_kind, self.resource_kind))
        if self.source_terrain_kind:
            bits.append("from %s" % self.source_terrain_kind)
        bits.append("at %d/hr" % self.base_rate)
        return " ".join(bits)


class SettlementBuilding(models.Model):
    
    kind = models.ForeignKey(BuildingKind)
    settlement = models.ForeignKey(Settlement)
    
    # location in settlement
    x = models.IntegerField()
    y = models.IntegerField()
    
    # build queue
    construction_start = models.DateTimeField(default=datetime.datetime.now)
    construction_end = models.DateTimeField(default=datetime.datetime.now)
    
    class Meta:
        unique_together = [("settlement", "x", "y")]
    
    def __unicode__(self):
        return u"%s on %s" % (self.kind, self.settlement)
    
    def build(self, commit=True):
        try:
            oldest = self.settlement.build_queue().reverse()[0]
        except IndexError:
            oldest = None
        
        # @@@ hard-coded two minute build times
        if oldest:
            self.construction_start = oldest.construction_end
        else:
            self.construction_start = datetime.datetime.now()
        self.construction_end = self.construction_start + datetime.timedelta(minutes=2)
        
        for product in self.kind.products.all():
            current = SettlementResourceCount.current(self.kind, settlement=self.settlement)
            amount = current.amount(self.construction_end)
            rate = product.base_rate # @@@ should be modified to use source_terrain_kind
            src = SettlementResourceCount(
                kind=current.kind,
                settlement=current.settlement,
                count=amount,
                timestamp=self.construction_end,
                natural_rate=current.natural_rate,
                rate_adjustment=current.rate_adjustment + rate,
                limit=0,
            )
            src.save()
        
        if commit:
            self.save()
    
    def status(self):
        now = datetime.datetime.now()
        if self.construction_start > now:
            return "queued"
        elif self.construction_end > now:
            return "under construction"
        else:
            return "built"


class SettlementBuildingResourceCount(BaseResourceCount):
    
    building = models.ForeignKey(SettlementBuilding)


class SettlementTerrainKind(models.Model):
    
    name = models.CharField(max_length=50)
    buildable_on = models.BooleanField(default=True)
    
    def __unicode__(self):
        return self.name


class SettlementTerrain(models.Model):
    
    kind = models.ForeignKey(SettlementTerrainKind)
    settlement = models.ForeignKey(Settlement, related_name="terrain")
    
    # location in settlement
    x = models.IntegerField()
    y = models.IntegerField()
    
    def __unicode__(self):
        return u"%s on %s" % (self.kind, self.settlement)


class SettlementTerrainResourceCount(BaseResourceCount):
    
    kind = models.ForeignKey(ResourceKind)
    terrain = models.ForeignKey(SettlementTerrain, related_name="resource_counts")
