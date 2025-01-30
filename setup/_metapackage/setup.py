import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo8-addons-akretion-jenji-connector",
    description="Meta package for akretion-jenji-connector Odoo addons",
    version=version,
    install_requires=[
        'odoo8-addon-jenji_connector',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 8.0',
    ]
)
