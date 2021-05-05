import json
import logging

from rest_framework import serializers

from mail.enums import LicenceActionEnum
from mail.models import Mail, LicenceData, UsageData, LicenceIdMapping


class LicenceDataSerializer(serializers.ModelSerializer):
    mail = serializers.PrimaryKeyRelatedField(queryset=Mail.objects.all(), required=False)

    class Meta:
        model = LicenceData
        fields = "__all__"

    def create(self, validated_data):
        instance, _ = LicenceData.objects.get_or_create(**validated_data)
        return instance


class LicenceDataMailSerializer(serializers.ModelSerializer):
    licence_data = LicenceDataSerializer(write_only=True)

    class Meta:
        model = Mail
        fields = [
            "id",
            "edi_filename",
            "edi_data",
            "extract_type",
            "raw_data",
            "licence_data",
        ]

    def create(self, validated_data):
        licence_data = validated_data.pop("licence_data")
        # Mail object should not exist for licence_data, so we can create it here safely

        dups = Mail.objects.filter(**validated_data)

        if dups and dups.first().response_data and "rejected" in dups.first().response_data:
            validated_data["retry"] = True
            mail = Mail.objects.create(**validated_data)
        else:
            mail, _ = Mail.objects.get_or_create(**validated_data)

        licence_data["mail"] = mail.id

        licence_data_serializer = LicenceDataSerializer(data=licence_data)
        if licence_data_serializer.is_valid():
            licence_data_serializer.save()
        else:
            logging.error(licence_data_serializer.errors)
            raise serializers.ValidationError(licence_data_serializer.errors)
        return mail


class UpdateResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mail
        fields = ["extract_type", "status", "response_filename", "response_data", "response_subject"]

        def update(self, instance, validated_data):
            instance.status = validated_data["status"]
            instance.response_file = validated_data["response_filename"]
            instance.response_data = validated_data["response_data"]
            instance.response_subject = validated_data["response_subject"]

            instance.save()

            return instance


class UsageDataSerializer(serializers.ModelSerializer):
    mail = serializers.PrimaryKeyRelatedField(queryset=Mail.objects.all(), required=False)

    class Meta:
        model = UsageData
        fields = ("licence_ids", "mail", "spire_run_number", "hmrc_run_number")

    def create(self, validated_data):
        validated_data["licence_ids"] = json.loads(validated_data["licence_ids"])

        has_lite_data = False
        has_spire_data = False

        for licence in validated_data["licence_ids"]:
            if LicenceIdMapping.objects.filter(reference=licence).exists():
                has_lite_data = True
            else:
                has_spire_data = True

            validated_data["has_lite_data"] = has_lite_data
            validated_data["has_spire_data"] = has_spire_data

        instance, created = UsageData.objects.get_or_create(**validated_data)

        if created and instance.has_lite_data:
            instance.send_usage_updates_to_lite(instance.id)

        return instance


class UsageDataMailSerializer(serializers.ModelSerializer):
    usage_data = UsageDataSerializer(write_only=True)

    class Meta:
        model = Mail
        fields = [
            "id",
            "edi_filename",
            "edi_data",
            "extract_type",
            "raw_data",
            "usage_data",
        ]

    def create(self, validated_data):
        usage_data = validated_data.pop("usage_data")
        mail, created = Mail.objects.get_or_create(**validated_data)

        usage_data["mail"] = mail.id

        if created:
            serializer = UsageDataSerializer(data=usage_data)
            if serializer.is_valid():
                serializer.save()
            else:
                raise serializers.ValidationError(serializer.errors)

        return mail


class GoodSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField(max_length=2000, allow_blank=True)
    quantity = serializers.DecimalField(decimal_places=3, max_digits=13)
    unit = serializers.CharField()


class CountrySerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class AddressSerializer(serializers.Serializer):
    line_1 = serializers.CharField(allow_blank=False)
    line_2 = serializers.CharField(allow_blank=True, required=False)
    line_3 = serializers.CharField(allow_blank=True, required=False)
    line_4 = serializers.CharField(allow_blank=True, required=False)
    line_5 = serializers.CharField(allow_blank=True, required=False)
    postcode = serializers.CharField(allow_blank=True, required=False)
    country = CountrySerializer()


class TraderSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, allow_blank=False)
    address = AddressSerializer()


class ForiegnTraderSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, allow_blank=False)
    address = AddressSerializer()


class LiteLicenceDataSerializer(serializers.Serializer):
    id = serializers.CharField()
    reference = serializers.CharField(max_length=35)
    type = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    action = serializers.CharField()

    old_id = serializers.CharField(required=False)

    def validate(self, attrs):
        if self.initial_data.get("action") == LicenceActionEnum.UPDATE and not attrs.get("old_id"):
            raise serializers.ValidationError("old_id is a required field for action - update")
        return attrs

    def validate_old_id(self, value):
        if (
            self.initial_data.get("action") == LicenceActionEnum.UPDATE
            and not LicenceIdMapping.objects.filter(lite_id=value).exists()
        ):
            raise serializers.ValidationError("This licence does not exist in HMRC integration records")
        return value
