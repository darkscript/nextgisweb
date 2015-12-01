# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import subprocess

import sqlalchemy as sa
import sqlalchemy.orm as orm

from osgeo import gdal, gdalconst, osr

from ..models import declarative_base
from ..resource import (
    Resource,
    DataStructureScope, DataScope,
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR,
    ResourceGroup)
from ..resource.exception import ValidationError
from ..env import env
from ..layer import SpatialLayerMixin
from ..file_storage import FileObj

Base = declarative_base()

SUPPORTED_GDT = (gdalconst.GDT_Byte, )

SUPPORTED_GDT_NAMES = ', '.join([
    gdal.GetDataTypeName(i)
    for i in SUPPORTED_GDT])


class RasterLayer(Base, Resource, SpatialLayerMixin):
    identity = 'raster_layer'
    cls_display_name = u"Растровый слой"

    __scope__ = (DataStructureScope, DataScope)

    fileobj_id = sa.Column(sa.ForeignKey(FileObj.id), nullable=True)

    xsize = sa.Column(sa.Integer, nullable=False)
    ysize = sa.Column(sa.Integer, nullable=False)
    band_count = sa.Column(sa.Integer, nullable=False)

    fileobj = orm.relationship(FileObj, cascade='all')

    @classmethod
    def check_parent(self, parent):
        return isinstance(parent, ResourceGroup)

    def load_file(self, filename, env):
        ds = gdal.Open(filename, gdalconst.GA_ReadOnly)
        if not ds:
            raise ValidationError("Библиотеке GDAL не удалось открыть файл")

        if ds.RasterCount not in (3, 4):
            raise ValidationError("Поддерживаются только растры RGB и RGBA")

        for bidx in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(bidx)

            if not band.DataType in SUPPORTED_GDT:
                raise ValidationError(
                    "Канал #%d имеет тип %s, однако поддерживаются " +
                    "только каналы следующих типов: %s." % (
                        bidx, gdal.GetDataTypeName(band.DataType),
                        SUPPORTED_GDT_NAMES))

        dsproj = ds.GetProjection()
        dsgtran = ds.GetGeoTransform()

        if not dsproj or not dsgtran:
            raise ValidationError("Растры без проекции не поддерживаются")

        src_osr = osr.SpatialReference()
        src_osr.ImportFromWkt(dsproj)
        dst_osr = osr.SpatialReference()
        src_osr.ImportFromEPSG(int(self.srs.id))

        reproject = not src_osr.IsSame(dst_osr)

        fobj = FileObj(component='raster_layer')

        dst_file = env.file_storage.filename(fobj, makedirs=True)
        self.fileobj = fobj

        if reproject:
            cmd = ['gdalwarp', '-of', 'GTiff',
                   '-t_srs', 'EPSG:%d' % self.srs.id]
            if ds.RasterCount == 3:
                cmd.append('-dstalpha')
        else:
            cmd = ['gdal_translate', '-of', 'GTiff']

        cmd.extend(('-co', 'TILED=YES', filename, dst_file))
        subprocess.check_call(cmd)

        ds = gdal.Open(dst_file, gdalconst.GA_ReadOnly)

        self.xsize = ds.RasterXSize
        self.ysize = ds.RasterYSize
        self.band_count = ds.RasterCount

    def gdal_dataset(self):
        fn = env.file_storage.filename(self.fileobj)
        return gdal.Open(fn, gdalconst.GA_ReadOnly)

    def get_info(self):
        s = super(RasterLayer, self)
        return (s.get_info() if hasattr(s, 'get_info') else ()) + (
            (u"Идентификатор файла", self.fileobj.uuid),
        )


class _source_attr(SP):

    def setter(self, srlzr, value):

        filedata, filemeta = env.file_upload.get_filename(value['id'])
        srlzr.obj.load_file(filedata, env)


P_DSS_READ = DataStructureScope.read
P_DSS_WRITE = DataStructureScope.write
P_DS_READ = DataScope.read
P_DS_WRITE = DataScope.write


class RasterLayerSerializer(Serializer):
    identity = RasterLayer.identity
    resclass = RasterLayer

    srs = SR(read=P_DSS_READ, write=P_DSS_WRITE)

    xsize = SP(read=P_DSS_READ)
    ysize = SP(read=P_DSS_READ)
    band_count = SP(read=P_DSS_READ)

    source = _source_attr(write=P_DS_WRITE)
